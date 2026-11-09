"""MCP stdio adapter for the parameterized kitchen-design application."""
from __future__ import annotations
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Literal
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.utilities.types import Image
from pydantic import ValidationError
from kitchen.intent import KitchenTemplate as KitchenTemplate
from kitchen.service import KitchenService
from kitchen.store import ConflictError
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('kitchen-design-mcp')
mcp = MCPServer('kitchen-design', description='Create, edit, validate, and render parameterized kitchen designs.', version='0.3.0')
_svc: KitchenService | None = None

def svc() -> KitchenService:
    global _svc
    if _svc is None:
        _svc = KitchenService()
    return _svc

def _call(function, *args, **kwargs):
    """Call a service function and convert expected failures into MCP tool errors."""
    try:
        return function(*args, **kwargs)
    except ConflictError as error:
        raise ToolError(f'Revision conflict: {error}') from error
    except ValidationError as error:
        validation_messages = '; '.join((f"{'.'.join(map(str, validation_error['loc']))}: {validation_error['msg']}" for validation_error in error.errors()[:5]))
        raise ToolError(f'Invalid data: {validation_messages}') from error
    except (KeyError, ValueError) as error:
        raise ToolError(str(error).strip('\'"')) from error

def create_design(template: KitchenTemplate | None=None, spec: dict[str, Any] | None=None, name: str='Kitchen design') -> dict[str, Any]:
    """Create a design from either a structured template or a complete specification."""
    if (template is None) == (spec is None):
        raise ToolError('Provide exactly one of template or spec.')
    return _call(svc().create_from_spec, spec) if spec is not None else _call(svc().create_from_template, template, name)

def list_floorplan_rooms(floorplan: dict[str, Any]) -> dict[str, Any]:
    """List the rooms (tag == "room") of an audited floorplan so one can be chosen for import."""
    return _call(lambda d: {"rooms": svc().list_floorplan_rooms(d)}, floorplan)


def import_floorplan(floorplan: dict[str, Any], name: str | None=None, room_id: str | None=None) -> dict[str, Any]:
    """Import one room of an audited floorplan JSON (room_id is required when the plan has several rooms); the source is kept once by hash."""
    return _call(svc().import_floorplan, floorplan, name, room_id)


def bind_floorplan(design_id: str, back_edge: int | None=None, offset: float=0.0, base_rev: int | None=None) -> dict[str, Any]:
    """Place the kitchen's back run against a wall of the imported room (auto-detected unless back_edge is given)."""
    return _call(svc().bind_floorplan, design_id, back_edge, offset, base_rev)

def design_kitchen(customer_prompt: str) -> dict[str, Any]:
    """Create a design by parsing a free-form customer request."""
    if not customer_prompt.strip():
        raise ToolError('customer_prompt must not be empty.')
    return _call(svc().create_from_prompt, customer_prompt)

def list_designs() -> list[dict[str, Any]]:
    """List saved designs and their latest revisions."""
    return svc().list_designs()

def get_design(design_id: str, rev: int | None=None) -> dict[str, Any]:
    """Return a complete design specification at the requested revision."""
    return _call(svc().get, design_id, rev)

def design_history(design_id: str) -> list[dict[str, Any]]:
    """Return the revision history for a design."""
    return _call(svc().history, design_id)

def add_module(design_id: str, base_rev: int, module: dict[str, Any], after_module: str | None=None, close_gap: bool=True, expect: str | None=None) -> dict[str, Any]:
    """Add a cabinet module to a design. expect: the opHash from propose_change, to refuse anything but the previewed operation."""
    return _call(svc().apply, design_id, {'op': 'add', 'module': module, 'afterModule': after_module, 'closeGap': close_gap}, base_rev, 'mcp', expect)

def update_module(design_id: str, base_rev: int, module_id: str, changes: dict[str, Any], close_gap: bool=True, expect: str | None=None) -> dict[str, Any]:
    """Update one cabinet module. expect: the opHash from propose_change."""
    return _call(svc().apply, design_id, {'op': 'update', 'id': module_id, 'changes': changes, 'closeGap': close_gap}, base_rev, 'mcp', expect)

def remove_module(design_id: str, base_rev: int, module_id: str, close_gap: bool=True, expect: str | None=None) -> dict[str, Any]:
    """Remove one cabinet module. expect: the opHash from propose_change."""
    return _call(svc().apply, design_id, {'op': 'remove', 'id': module_id, 'closeGap': close_gap}, base_rev, 'mcp', expect)

def update_global(design_id: str, base_rev: int, changes: dict[str, Any], expect: str | None=None) -> dict[str, Any]:
    """Update shared design parameters. expect: the opHash from propose_change."""
    return _call(svc().apply, design_id, {'op': 'common', 'changes': changes}, base_rev, 'mcp', expect)

def set_moldings(design_id: str, base_rev: int, crown_molding: bool=True, base_molding: bool=True, crown_profile: str='classic-crown-layered', base_profile: str='classic-base', style: Literal['Modern', 'Classic', 'Neoclassical', 'Transitional', 'Industrial', 'Minimalist'] | None='Classic', open_end: Literal['return-to-wall', 'flat-cut']='return-to-wall') -> dict[str, Any]:
    """Enable or disable crown and base moldings using selected profiles."""
    return _call(svc().set_moldings, design_id, base_rev, crown_molding, base_molding, crown_profile, base_profile, style, open_end, 'mcp')

def list_molding_profiles(design_id: str | None=None) -> dict[str, Any]:
    """List built-in and design-specific molding profiles."""
    return _call(svc().molding_profiles, design_id)

def apply_action(design_id: str, base_rev: int, op: dict[str, Any], expect: str | None=None) -> dict[str, Any]:
    """Apply a supported corrective action returned by design validation. expect: the opHash from propose_change."""
    if op.get('op') not in ('lower-top', 'molding', 'set-moldings'):
        raise ToolError('Unsupported corrective action. Use a design-editing tool for other operations.')
    return _call(svc().apply, design_id, op, base_rev, 'mcp-action', expect)

def propose_change(design_id: str, op: dict[str, Any], base_rev: int | None=None, scope_modules: list[str] | None=None) -> dict[str, Any]:
    """Preview a design operation without saving: changes, validation issues it introduces or resolves, and the modules it touches.

    Confirm by sending the same op to the matching editing tool (add_module, update_module, remove_module, update_global, apply_action) with the returned baseRev and expect=opHash; anything else is refused. scope_modules: ids the user pointed at.
    """
    return _call(svc().propose, design_id, op, base_rev, scope_modules)

def interpret_edit(design_id: str, text: str, base_rev: int | None=None, scope_modules: list[str] | None=None, use_llm: bool=False) -> dict[str, Any]:
    """Turn a free-form edit sentence (e.g. 'xóa TD3', 'tủ trên đổi cánh kính') into a previewed operation; nothing is saved.

    status 'ok' returns operation + proposal (same as propose_change): confirm with the matching editing tool and expect=proposal.opHash.
    status 'clarify' returns a question (and choices) to put to the user; 'unsupported' means the sentence was not understood.
    use_llm lets DeepSeek try only when the rules cannot read the sentence and a key is configured.
    """
    return _call(svc().interpret, design_id, text, base_rev, scope_modules, None, use_llm)

def recognize_design(design_id: str, source: dict[str, Any], recognizer: str | None=None, base_rev: int | None=None) -> dict[str, Any]:
    """Recognise a photo or drawing as a DRAFT kitchen and preview it; nothing is saved.

    source: {"kind": "photo" | "drawing", "imageBase64": "...", "name"?: "...", "note"?: "hint about the picture, max 500 chars"}.
    recognizer: "cabinet" (the stand-alone cabinet-recognizer, CABINET_RECOGNIZER_URL) or "gemini"; omitted = KITCHEN_RECOGNIZER, else cabinet, else gemini.
    The draft replaces ALL cabinets of the design (room, floor plan and common settings are kept). status 'ok' returns draft + operation + proposal (same as propose_change):
    confirm with the editing tool and expect=proposal.opHash. 'unavailable' = no recognizer is plugged in; 'empty' = nothing usable recognised.
    """
    return _call(svc().recognize, design_id, source, recognizer, base_rev)

def propose_template(design_id: str, template: dict[str, Any], base_rev: int | None=None) -> dict[str, Any]:
    """Preview a cabinet template against an object of the imported floorplan; nothing is saved.

    template: {"kind": "run-i", "structureId": "STRUCT-...", "point": {"x": mm, "z": mm}} - a straight run of base cabinets along the edge of the object
    nearest to point (room frame), doors facing away from the object. Confirm with the editing tool and expect=proposal.opHash.
    """
    return _call(svc().template, design_id, template, base_rev)

def revert_design(design_id: str, base_rev: int, target_revision: int) -> dict[str, Any]:
    """Create a new revision matching an earlier revision."""
    return _call(svc().revert, design_id, target_revision, base_rev)

def validate_design(design_id: str, rev: int | None=None, country: str | None=None, region: str | None=None) -> dict[str, Any]:
    """Validate geometry and applicable knowledge rules."""
    return _call(svc().validate, design_id, rev, country, region)

def get_scene(design_id: str, rev: int | None=None) -> dict[str, Any]:
    """Return the compiled geometry scene for a design."""
    return _call(svc().scene, design_id, rev)

def export_threejs(design_id: str, rev: int | None=None, country: str | None=None, include_document: bool=False) -> dict[str, Any]:
    """Export and validate a Three.js scene document."""
    return _call(svc().export_threejs_file, design_id, rev, country, include_document)

def render_views(design_id: str, rev: int | None=None, views: list[str] | None=None, width: int=1280, height: int=960, include_images: Literal['none', 'lines', 'lines+depth']='lines') -> list[Any]:
    """Render control images for the selected design views."""
    res = _call(svc().render, design_id, rev, views, width, height)
    out: list[Any] = [json.dumps(res, ensure_ascii=False, indent=1)]
    if include_images != 'none':
        kinds = ['lines'] + (['depth'] if include_images == 'lines+depth' else [])
        for view_result in res['views'].values():
            for image_kind in kinds:
                out.append(Image(path=f"{view_result['dir']}/{image_kind}.png"))
    return out

def search_knowledge(query: str='', kinds: list[Literal['standard', 'rule', 'material']] | None=None, country: str | None=None, region: str | None=None, region_only: bool=False) -> dict[str, Any]:
    """Search standards, rules, and materials with regional prioritization."""
    return {'items': _call(svc().search_knowledge, query, kinds, country, region, region_only)}

def list_regions() -> dict[str, Any]:
    """List supported regions, countries, and knowledge counts."""
    return svc().list_regions()

def add_knowledge(kind: Literal['standard', 'rule', 'material'], code: str, title: str, content: str, source_url: str='', metadata: dict[str, Any] | None=None, region: str='GLOBAL', country: str='') -> dict[str, Any]:
    """Insert or update a knowledge entry."""
    return _call(svc().add_knowledge, kind=kind, code=code, title=title, content=content, source_url=source_url, metadata=metadata, region=region, country=country)

def export_ai_package(design_id: str, rev: int | None=None, views: list[str] | None=None, include_images: bool=True, country: str | None=None, embed_images: bool=False, lighting: Literal['daylight', 'late-afternoon', 'dim-evening']='daylight') -> dict[str, Any]:
    """Build an AI image-generation package for a design."""
    res = _call(svc().ai_export, design_id, rev, views, country, include_images, False, lighting)
    if embed_images:
        res['embeddedImagesFile'] = _call(svc().ai_export, design_id, rev, views, country, False, True, lighting)['file']
    return res

def _slim_job(job: dict) -> dict:
    result = job['result']
    return {'id': job['id'], 'status': job['status'], 'error': job['error'], 'kind': job['kind'], 'mode': job['mode'], 'target': job['target'], 'backend': job['backend'], 'view': job['view'], 'rev': job['rev'], 'renderKey': job['render_key'], 'dir': result.get('dir'), 'scope': job['request'].get('scope'), 'prompt': job['request'].get('prompt'), 'report': result.get('report'), 'design': result.get('design'), 'package': result.get('package'), 'requestFile': str(Path(result['dir']) / 'request.json') if result.get('dir') and (Path(result['dir']) / 'request.json').exists() else None, 'tasks': [{image_kind: t.get(image_kind) for image_kind in ('targetLayer', 'material', 'instruction', 'scope', 'maskPixels')} for t in job['request'].get('tasks') or []]}

def list_layers(design_id: str, view: str, rev: int | None=None, include_all: bool=False) -> dict[str, Any]:
    """List selectable image layers for a rendered view."""
    result = _call(svc().images.layers, design_id, view, rev, include_all)
    result['layers'] = [{image_kind: view_result for image_kind, view_result in validation_error.items() if image_kind not in ('allowGeometryChange', 'allowPositionChange', 'selectable')} for validation_error in result['layers']]
    return result

def get_view_status(design_id: str, rev: int | None=None) -> dict[str, Any]:
    """Per view: does the approved image still match the design (current / stale-appearance / stale-geometry / unknown / none)?"""
    return _call(lambda: {'views': svc().images.view_status(design_id, rev)})

def regenerate_stale_views(design_id: str, views: list[str] | None=None, backend: Literal['recolor', 'job-package', 'gemini']='recolor', base_rev: int | None=None) -> dict[str, Any]:
    """Prepare review jobs (not sent) that re-apply changed materials onto the approved images of the stale views."""
    return _call(svc().images.regenerate_stale, design_id, views, backend, base_rev)

def create_image_job(design_id: str, view: str, target_layer: str | None=None, instruction: str='', mode: Literal['quick', 'design']='quick', material: str | None=None, backend: Literal['recolor', 'job-package', 'gemini']='recolor', kind: Literal['edit', 'gen0', 'geometry_edit']='edit', reference: str | None=None, base_rev: int | None=None, seed: int | None=None, tasks: list[dict[str, Any]] | None=None, preview_only: bool=False, image_changes: list[dict[str, Any]] | None=None, operation: Literal['change-material', 'replace-item', 'remove-item', 'add-item', 'change-style'] | None=None, lighting: Literal['daylight', 'late-afternoon', 'dim-evening'] | None=None, style_from: str | None=None) -> dict[str, Any]:
    """Create an image-generation or image-editing job. style_from: 'auto' or a view name whose approved image guides materials and light (automatic for a first image; 'none' turns it off)."""
    return _slim_job(_call(svc().images.create, design_id, view, target_layer, instruction=instruction, mode=mode, material=material, backend=backend, reference=reference, base_rev=base_rev, kind=kind, seed=seed, tasks=tasks, preview=preview_only, geometry_items=image_changes, operation=operation, lighting=lighting, style_from=style_from))

def send_image_job(job_id: str) -> dict[str, Any]:
    """Send a prepared image job to its configured backend."""
    return _slim_job(_call(svc().images.send, job_id))

def get_image_job(job_id: str, wait_seconds: float=0) -> dict[str, Any]:
    """Return image-job status and details, optionally waiting for completion."""
    if wait_seconds > 0:
        return _slim_job(_call(svc().images.wait, job_id, min(wait_seconds, 300)))
    return _slim_job(_call(svc().images.get, job_id))

def list_image_jobs(design_id: str | None=None, view: str | None=None, status: str | None=None) -> dict[str, Any]:
    """List image jobs, newest first."""
    return {'items': [_slim_job(job) for job in _call(svc().images.list, design_id, view, status)]}

def submit_image_result(job_id: str, image_path: str) -> dict[str, Any]:
    """Submit an image file as the result of an externally processed job."""
    from pathlib import Path
    source_image = Path(image_path).expanduser()
    if not source_image.is_file():
        raise ToolError(f'Image file not found: {source_image}')
    return _slim_job(_call(svc().images.submit_result, job_id, source_image.read_bytes()))

def import_base_image(design_id: str, view: str, image_path: str, rev: int | None=None, fit: Literal['reject', 'crop', 'pad']='reject') -> dict[str, Any]:
    """Replace the base image of a view with a fully lit image made elsewhere (e.g. ChatGPT). Later edit jobs use it as the base image."""
    from pathlib import Path
    source_image = Path(image_path).expanduser()
    if not source_image.is_file():
        raise ToolError(f'Image file not found: {source_image}')
    info = _call(svc().images.import_base, design_id, view, source_image.read_bytes(), rev, 'MCP import', fit)
    info.pop('dir', None)
    return info

def accept_image_job(job_id: str, apply_to_design: bool=False, base_rev: int | None=None) -> dict[str, Any]:
    """Accept an image result and optionally apply its design changes."""
    return _slim_job(_call(svc().images.accept, job_id, apply_to_design, base_rev))

def reject_image_job(job_id: str) -> dict[str, Any]:
    """Reject an image result."""
    return _slim_job(_call(svc().images.reject, job_id))

def regenerate_image_job(job_id: str, seed: int | None=None) -> dict[str, Any]:
    """Create a replacement job with the same request and a new seed."""
    return _slim_job(_call(svc().images.regenerate, job_id, seed))
TOOLS = [create_design, list_floorplan_rooms, import_floorplan, bind_floorplan, design_kitchen, list_designs, get_design, design_history, add_module, update_module, remove_module, update_global, set_moldings, list_molding_profiles, apply_action, propose_change, interpret_edit, recognize_design, propose_template, revert_design, validate_design, get_scene, export_threejs, render_views, search_knowledge, list_regions, add_knowledge, export_ai_package, list_layers, get_view_status, regenerate_stale_views, create_image_job, get_image_job, list_image_jobs, submit_image_result, import_base_image, accept_image_job, reject_image_job, regenerate_image_job, send_image_job]
for tool_function in TOOLS:
    mcp.add_tool(tool_function, name=tool_function.__name__, description=(tool_function.__doc__ or '').strip(), structured_output=False if tool_function is render_views else None)

def main() -> None:
    logger.info('Starting kitchen-design MCP server (stdio), %d tools', len(TOOLS))
    server = svc()
    logger.info('SQLite: %s · renders: %s', server.store.path, server.render_dir)
    try:
        mcp.run('stdio')
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info('MCP server stopped')
if __name__ == '__main__':
    main()
