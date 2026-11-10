"""Shared application service used by the MCP server and HTTP API."""
from __future__ import annotations
import base64
import binascii
import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any, Callable
from . import cabinet_run, run_line, run_template, runs, edit, edit_intent, geometry, intent, llm, recognition, regions, roomctx, render, rules, threejs_export
from .intent import KitchenTemplate as KitchenTemplate
from .spec import Common, KitchenSpec, Room, Wall, dump_spec, load_spec, to_data
from .store import ConflictError, Store
from . import legacy as legacy_schema
from .config import Config
from .errors import InvalidInput, NotFound
ROOT = Path(__file__).resolve().parent.parent

def load_dotenv(path: Path=ROOT / '.env') -> None:
    """Load KEY=VALUE entries without overriding existing environment values."""
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and (not line.startswith('#')) and ('=' in line):
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

def utc_now() -> str:
    """The shell's clock: ISO-8601 UTC, whole seconds."""
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


class KitchenService:
    """Coordinate design, persistence, validation, geometry, and image jobs."""

    def __init__(self, db_path: str | Path | None=None, render_dir: str | Path | None=None, clock: Callable[[], str] | None=None):
        load_dotenv()
        self.clock = clock or utc_now
        self.config = Config.from_env()      # the environment is read here, once; below this line the service uses the value
        self.store = Store(db_path or self.config.db_path)
        self.recognizers: dict[str, recognition.Recognizer] = {}     # plug-ins; the Gemini reader is wired when a key is available
        self._wire_recognizers()
        self.render_dir = Path(render_dir or self.config.render_dir)
        legacy_schema.migrate_renders(self.render_dir)
        from .images import ImageJobs
        self.images = ImageJobs(self.store, self.render_dir, self.apply, self.config)

    def _summary(self, design_id: str, revision: int, spec: KitchenSpec, **extra) -> dict:
        """Build the established API summary for a design revision."""
        validation = self.validate_spec(spec)
        return {'id': design_id, 'rev': revision, 'name': spec.name, 'moduleCount': len(spec.module), 'country': spec.country, 'region': spec.region, 'module': [{'id': module.id, 'type': module.type, 'wall': module.wall, 'fromCorner': module.fromCorner, 'width': module.width, 'y': module.y, 'height': module.height} for module in spec.module], 'validation': {'valid': validation['valid'], 'dem': validation['dem'], 'issues': validation['issues'][:20]}, 'cameraViews': list(geometry.views_of(spec)), **extra}

    def create_from_spec(self, spec_data: dict | KitchenSpec, source: str='spec', **legacy: Any) -> dict:
        """Create and persist a design from a complete specification."""
        source = legacy.pop('source', source)
        if legacy:
            raise TypeError(f"Unexpected options: {', '.join(legacy)}")
        spec = spec_data if isinstance(spec_data, KitchenSpec) else load_spec(spec_data)
        record = self.store.create_design(spec, source)
        return self._summary(record['id'], 1, spec)

    def list_floorplan_rooms(self, data: dict[str, Any]) -> list[dict]:
        """List the rooms of an audited floorplan without importing anything."""
        from .floorplan import list_rooms
        return list_rooms(data)

    def import_floorplan(self, data: dict[str, Any], name: str | None=None, room_id: str | None=None) -> dict:
        """Validate an audited floorplan, keep its source once (by hash), and create a room-only design for one room."""
        from .floorplan import normalize
        fp = normalize(data, room_id)
        self.store.put_floorplan(fp['ref'], data)
        base_name = name or str(data.get('planId') or 'Floorplan design')
        spec = KitchenSpec(name=base_name, source='Imported audited floorplan', common=Common(ceiling=fp['height']), room=None, floorplan=fp)
        record = self.store.create_design(spec, 'floorplan-import')
        outside = [e['id'] for e in fp['elements'] if e.get('membership') == 'outside']
        unattached = [e['id'] for e in fp['elements'] if e.get('tag') in ('door', 'window') and not e.get('attached')]
        return self._summary(record['id'], record['rev'], spec, floorplan={
            'ref': fp['ref'], 'roomId': fp['roomId'], 'roomLabel': fp.get('roomLabel'), 'width': fp['width'], 'depth': fp['depth'],
            'areaM2': fp['areaM2'], 'rooms': fp['rooms'], 'counts': fp['counts'], 'wallCount': len(fp['walls']),
            'outsideElements': outside, 'unattachedOpenings': unattached, 'warnings': fp['warnings']})

    def bind_floorplan(self, design_id: str, back_edge: int | None=None, offset: float=0.0, base_revision: int | None=None) -> dict:
        """Place the kitchen against a wall of the imported room (auto-picked unless ``back_edge`` is given)."""
        from .floorplan import bind_kitchen
        spec, _rev = self.store.get(design_id)
        fp = spec.floorplan
        if not isinstance(fp, dict):
            raise InvalidInput('The design has no imported floorplan')
        if not spec.module:
            raise InvalidInput('The design has no cabinets to place')
        scene = geometry.compile_spec(spec)
        used = runs.walls_used(spec, scene.lsau)
        need = {'back': scene.lsau, 'right': scene.lphai if 'right' in used else 0, 'left': scene.lphai if 'left' in used else 0}
        binding = bind_kitchen(fp, need, back_edge, offset)
        spec.floorplan = {**fp, 'binding': binding}
        revision = self.store.add_revision(design_id, base_revision, spec, {'op': 'bind-floorplan', 'back': binding['back'], 'source': binding['source']}, 'bind-floorplan')
        return {'id': design_id, 'rev': revision, 'binding': binding}

    @staticmethod
    def _by_runs(spec: KitchenSpec) -> KitchenSpec:
        """A newly generated kitchen written by explicit runs (``rows_to_runs``): the generator still thinks in walls, a design is stored by runs.
        Kept as generated if the rewritten kitchen would not compile to the very same boxes."""
        from . import rows_to_runs
        data, _ = rows_to_runs.convert(spec)
        after = KitchenSpec.model_validate(data)
        return spec if rows_to_runs.equivalent(spec, after) else after

    def create_from_template(self, template: dict | KitchenTemplate, name: str='Kitchen design', **legacy: Any) -> dict:
        """Generate and persist a design from a structured template."""
        name = legacy.pop('name', name)
        if legacy:
            raise TypeError(f"Unexpected options: {', '.join(legacy)}")
        parsed_template = template if isinstance(template, KitchenTemplate) else KitchenTemplate.model_validate(template)
        spec = self._by_runs(intent.from_template(parsed_template, name, self.store.rule_rows()))
        record = self.store.create_design(spec, 'template')
        return self._summary(record['id'], 1, spec, color=parsed_template.model_dump())

    def create_from_prompt(self, prompt: str, name: str | None=None, **legacy: Any) -> dict:
        """Parse free-form text and create a design, falling back to regex parsing."""
        name = legacy.pop('name', name)
        if legacy:
            raise TypeError(f"Unexpected options: {', '.join(legacy)}")
        template, llm_result = llm.parse_prompt_llm(prompt, self.config)
        notes: list[str] = []
        parser_source = 'deepseek'
        if template is None:
            template, notes = intent.parse_prompt(prompt)
            parser_source = 'regex'
        else:  # DeepSeek không biết các trường mới (phong cách, kiểu cánh, tay nắm, ốp): bổ sung từ bảng thuật ngữ
            template, notes = intent.merge_lexicon(template, prompt)
        spec = self._by_runs(intent.from_template(template, name or prompt[:60], self.store.rule_rows()))
        record = self.store.create_design(spec, f'prompt:{parser_source}')
        return self._summary(record['id'], 1, spec, color=template.model_dump(), analysis={'source': parser_source, 'note': notes, 'interpretation': template.promptInterpretation, 'deepseek': llm_result})

    def get(self, design_id: str, revision: int | None=None) -> dict:
        """Return a design specification at the requested or latest revision."""
        spec, stored_revision = self.store.get(design_id, revision)
        return {'id': design_id, 'rev': stored_revision, 'spec': dump_spec(spec)}

    def apply(self, design_id: str, operation: dict[str, Any], base_revision: int | None, source: str='', expect: str | None=None, **legacy: Any) -> dict:
        """Apply one operation and append a revision, rejecting stale base revisions.

        ``expect``: the ``opHash`` that :meth:`propose` returned. When given, the operation and base revision must be exactly the
        previewed ones, so what is saved is what the user saw.
        """
        source = legacy.pop('source', source)
        if legacy:
            raise TypeError(f"Unexpected options: {', '.join(legacy)}")
        if expect is not None:
            from . import proposal
            if base_revision is None or proposal.op_hash(operation, base_revision) != expect:
                raise InvalidInput('The operation differs from the one that was previewed; preview it again before confirming', code='operation-differs-from-preview')
        spec, _current_revision = self.store.get(design_id)
        updated_spec = edit.apply_op(spec, operation)
        new_revision = self.store.add_revision(design_id, base_revision, updated_spec, operation, source)
        return self._summary(design_id, new_revision, updated_spec)

    def interpret(self, design_id: str, text: str, base_revision: int | None=None, scope: list[str] | None=None,
                  country: str | None=None, use_llm: bool=False) -> dict:
        """Free-form edit sentence -> a previewed operation, never saved. Send ``operation`` to :meth:`apply` with ``proposal.opHash`` to confirm.

        ``status`` is ``ok`` (with ``operation``, ``summary`` and the full :meth:`propose` result under ``proposal``), ``clarify`` (a
        ``question`` and optional ``choices``) or ``unsupported``. ``use_llm`` asks DeepSeek only when the rules cannot read the sentence
        and a key is configured; its operation passes ``edit_intent.check_operation`` and then ``propose`` like any other.
        """
        spec, current = self.store.get(design_id)
        if base_revision is not None and base_revision != current:
            raise ConflictError(f'base_rev={base_revision}, but the latest revision is {current}; reload before editing')
        result = edit_intent.interpret_edit(spec, text, scope)
        if result['status'] == 'unsupported' and use_llm:
            guess, status = llm.edit_operation_llm(text, spec, self.config)
            result = edit_intent.check_operation(guess) if guess else {**result, 'llm': status}
        if result['status'] != 'ok':
            return {'id': design_id, 'baseRev': current, **result}
        preview = self.propose(design_id, result['operation'], current, scope or result.get('targets') or None, country)
        return {'id': design_id, 'baseRev': current, **result, 'proposal': preview}

    def template(self, design_id: str, template: dict[str, Any], base_revision: int | None=None, country: str | None=None) -> dict:
        """A cabinet template standing against an object of the imported floorplan, or on a line the user drew, previewed and never saved.

        ``{"kind": "run-line", "a": {x, z}, "b": {x, z}, "front": {x, z}, "prompt"?}`` (room frame, mm): a run from ``a`` to ``b`` with its doors
        looking at the side ``front`` is on; base cabinets fill it, or the cabinets ``prompt`` describes. Works without a floorplan too.

        ``template``: ``{"kind": "run-i", "structureId": "STRUCT-...", "point": {"x": mm, "z": mm}}`` where ``point`` (room frame, e.g. where the
        user clicked) picks the edge. The doors face away from the object. The result carries ``operation``, ``facing``, ``summary`` and the
        :meth:`propose` result under ``proposal``; confirm with :meth:`apply` and its opHash.
        """
        spec, current = self.store.get(design_id)
        if base_revision is not None and base_revision != current:
            raise ConflictError(f'base_rev={base_revision}, but the latest revision is {current}; reload before editing')
        if template.get('kind') == 'corner':     # {"kind": "corner", "runA": "R1", "runB": "R2", "width"?: mm}: special corner cabinet between two runs
            plan = cabinet_run.plan_corner(spec, str(template.get('runA')), str(template.get('runB')), float(template.get('width') or 900.0))
            preview = self.propose(design_id, plan['operation'], current, None, country)
            return {'id': design_id, 'baseRev': current, 'status': 'ok', 'facing': None, 'angle': plan['angle'], 'clearance': plan['clearance'], 'length': template.get('width') or 900.0,
                    'summary': plan['summary'], 'operation': plan['operation'], 'proposal': preview}
        if template.get('kind') == 'run-line':   # {"kind": "run-line", "a": {x, z}, "b": {x, z}, "front": {x, z}, "prompt"?}: a run on a drawn line
            plan = self._plan_on_drawn_line(spec, template, country)
            preview = self.propose(design_id, plan['operation'], current, None, country)
            return {'id': design_id, 'baseRev': current, 'status': 'ok', 'facing': None, 'run': plan['run'], 'length': plan['length'],
                    'summary': plan['summary'], 'operation': plan['operation'], 'proposal': preview}
        if template.get('kind') != 'run-i':
            raise InvalidInput("template.kind must be 'run-i', 'run-line' or 'corner'", code='bad-template-kind')
        point = template.get('point')
        if not isinstance(point, dict) or not all(isinstance(point.get(k), (int, float)) for k in ('x', 'z')):
            raise InvalidInput('template.point needs numeric x and z (mm, room frame)', code='bad-template-point')
        prompt = template.get('prompt')
        if isinstance(prompt, str) and prompt.strip():      # a described kitchen: fridge, loft row, worktop colour, door colours...
            color, notes = intent.parse_prompt(prompt)
            if not color.country and country:
                color = color.model_copy(update={'country': country})
            planner = lambda outline, click, system: self._plan_described(spec, color, notes, outline, click, system)
        else:
            planner = lambda outline, click, system: cabinet_run.plan_i_run(spec, outline, click, system=system)
        struct, plan = self._plan_at_object(spec, str(template.get('structureId')), point, planner)
        preview = self.propose(design_id, plan['operation'], current, None, country)
        return {'id': design_id, 'baseRev': current, 'status': 'ok', 'structureId': struct['id'], 'facing': plan['facing'], 'length': plan['length'],
                'summary': plan['summary'], 'operation': plan['operation'], 'proposal': preview}

    @staticmethod
    def _plan_described(spec: KitchenSpec, color: KitchenTemplate, notes: list[str], outline: list, click: tuple, system: str | None = None) -> dict:
        """The cabinets a sentence describes, in a run along the edge of the object nearest to ``click`` (kitchen frame). The run is as long as
        the edge unless the sentence gives a length; what the sentence says about materials and handles joins the design's own."""
        return KitchenService._plan_described_line(spec, color, notes, run_line.edge_line(outline, click), system)

    @staticmethod
    def _plan_described_line(spec: KitchenSpec, color: KitchenTemplate, notes: list[str], line: Any, system: str | None = None) -> dict:
        """The cabinets a sentence describes, in a run on ``line`` (kitchen frame)."""
        length = float(color.backWallLength) if 'backWallLength' in color.model_fields_set else run_line.run_frame(line)['length'] // 10 * 10
        if length < 600:
            raise InvalidInput(f'The edge is only {length:g} mm long; a run needs at least 600 mm', code='edge-too-short')
        built = run_template.run_from_template(color, length)
        changes = dict(built['common'])
        if 'material' in changes:
            changes['material'] = {**spec.common.material, **changes['material']}
        after = [{'op': 'common', 'changes': changes}] if changes else []
        plan = run_line.plan_on_line(spec, line, built['modules'], after=after, system=system)
        made = sorted({m['type'] for m in built['modules']})
        explicit = 'backWallLength' in color.model_fields_set
        kept = [n for n in notes if explicit or 'chiều dài' not in n]          # the "no length given, 3000 mm" note does not apply: the edge sets it
        plan['summary'] = [*plan['summary'], f"From the description: {', '.join(made)}", *kept]
        plan['facing'] = None
        return plan

    def _settle(self, spec: Any, planner: Callable[[Any], dict], place: Any) -> dict:
        """``planner(place)`` run in the kitchen frame the design will have once the plan is in (``place``: room frame <-> kitchen frame). A design
        without cabinets has no wall binding yet, so its kitchen frame is the room frame; the first cabinet binds the kitchen to a wall and moves that
        frame, so plan again until the plan and the frame agree."""
        from .placement import IDENTITY
        plan: dict = {}
        for _ in range(3):
            plan = planner(place)
            try:
                after = edit.apply_op(spec.model_copy(deep=True), plan['operation'])
                scene_after = geometry.compile_spec(after)
                ctx_after = roomctx.for_spec(after, scene_after.lsau, scene_after.lphai)
            except Exception:       # the preview reports an operation that cannot be applied
                break
            place_after = ctx_after.placement if ctx_after is not None and ctx_after.placement is not None else IDENTITY
            if place_after == place:
                break
            place = place_after
        return plan

    def _plan_at_object(self, spec: Any, structure_id: str, point: dict[str, Any],
                        planner: Callable[[list[tuple[float, float]], tuple[float, float], str | None], dict]) -> tuple[dict, dict]:
        """``(object, plan)``: ``planner(outline, click, system)`` run with the object's outline and the click in the KITCHEN frame (see ``_settle``)
        and the cabinet system of what stands against it: the id of the floorplan element (``elements[].id``, the structure's ``sourceElement``),
        the same each time something is made against that element. ``point`` is in the room frame (mm)."""
        from .placement import IDENTITY
        scene = geometry.compile_spec(spec)
        ctx = roomctx.for_spec(spec, scene.lsau, scene.lphai)
        if ctx is None:
            raise InvalidInput('This design has no imported floorplan, so there is no object to stand against', code='no-floorplan')
        struct = next((s for s in ctx.structures if s['id'] == structure_id), None)
        if struct is None:
            raise NotFound(f"No such object: {structure_id}", code='structure-not-found')
        click = (float(point['x']), float(point['z']))
        system = runs.system_id(struct.get('sourceElement') or str(struct['id']).removeprefix('STRUCT-'))
        plan = self._settle(spec, lambda place: planner([place.to_kitchen(float(p['x']), float(p['z'])) for p in struct['outline']], place.to_kitchen(*click), system),
                            ctx.placement if ctx.placement is not None else IDENTITY)
        return struct, plan

    def _plan_on_drawn_line(self, spec: Any, template: dict[str, Any], country: str | None) -> dict:
        """A run along a line the user drew: ``{"a": {x, z}, "b": {x, z}, "front": {x, z}, "prompt"?}`` (room frame, mm; ``front``: any point on the
        side the doors look at). Without a prompt the line is filled with base cabinets; with one, with the cabinets the sentence describes."""
        from .placement import IDENTITY
        pts = {}
        for key in ('a', 'b', 'front'):
            p = template.get(key)
            if not isinstance(p, dict) or not all(isinstance(p.get(k), (int, float)) and not isinstance(p.get(k), bool) for k in ('x', 'z')):
                raise InvalidInput(f'template.{key} needs numeric x and z (mm, room frame)', code='bad-line')
            pts[key] = (float(p['x']), float(p['z']))
        prompt = template.get('prompt')
        described = intent.parse_prompt(prompt) if isinstance(prompt, str) and prompt.strip() else None

        def planner(place: Any) -> dict:
            line = run_line.drawn_line(place.to_kitchen(*pts['a']), place.to_kitchen(*pts['b']), place.to_kitchen(*pts['front']))
            if described is not None:
                color, notes = described
                if not color.country and country:
                    color = color.model_copy(update={'country': country})
                return self._plan_described_line(spec, color, notes, line)
            return run_line.plan_on_line(spec, line, run_line.base_cabinets(run_line.run_frame(line)['length'], to_data(spec)['common']))

        scene = geometry.compile_spec(spec)
        ctx = roomctx.for_spec(spec, scene.lsau, scene.lphai)
        return self._settle(spec, planner, ctx.placement if ctx is not None and ctx.placement is not None else IDENTITY)

    def _wire_recognizers(self) -> None:
        from .backends import BackendError
        from .recognizers import CabinetInboxHttp, CabinetRecognizerHttp, GeminiRecognizer
        for name, make in (("gemini", GeminiRecognizer), ("cabinet", CabinetRecognizerHttp), ("inbox", CabinetInboxHttp)):
            try:
                self.recognizers[name] = make(self.config)
            except BackendError:
                pass                # no key / no service URL: that recognizer is simply not offered; with none, recognition answers "unavailable"

    def register_recognizer(self, name: str, recognizer: recognition.Recognizer) -> None:
        """Plug in a photo/drawing recognizer (anything with ``recognize(RecognitionInput) -> dict``)."""
        self.recognizers[name] = recognizer

    def recognize(self, design_id: str, source: dict[str, Any], recognizer: str | None=None, base_revision: int | None=None,
                  country: str | None=None, anchor: dict[str, Any] | None=None, mode: str='add') -> dict:
        """Photo or drawing -> a DRAFT kitchen, previewed, never saved. ``source``: ``{"kind": "photo"|"drawing", "imageBase64": "...", "name"?, "mediaType"?, "note"?}`` (``note``: the user's hint, up to 500 characters).

        Every recognition is placed BY RUNS (explicit runs, each cabinet with what it carries): a recognizer that gives the kitchen by runs
        (cabinet-recognizer: recognized-runs/1) as it is, one that gives a flat draft (wall + fromCorner) after ``runs_from_draft``. An L or U has its
        side runs square to the main one. ``anchor`` (``{"structureId", "point": {"x", "z"}}``, room frame, mm): the main run stands along the edge of
        that floor-plan object nearest to the point, doors facing away from it, ADDED to the cabinets already there (``mode="replace"``: instead of
        them). Without an anchor the main run stands along the back wall of the kitchen frame and the design's cabinets are replaced. Replacing also
        takes the recognised levels, ceiling and materials into ``common``.

        ``status``: ``ok`` (``draft`` + ``operation`` + the :meth:`propose` result under ``proposal``; confirm with :meth:`apply` and its opHash),
        ``empty`` (nothing usable was recognised), ``unavailable`` (no recognizer plugged in) or ``failed`` (the recognizer raised).
        """
        spec, current = self.store.get(design_id)
        if base_revision is not None and base_revision != current:
            raise ConflictError(f'base_rev={base_revision}, but the latest revision is {current}; reload before editing')
        kind = source.get('kind')
        if kind not in recognition.contract.SOURCE_KINDS:
            raise InvalidInput(f"source.kind must be one of {', '.join(recognition.contract.SOURCE_KINDS)}", code='bad-source-kind')
        try:
            data = base64.b64decode(str(source.get('imageBase64') or ''), validate=True)
        except (binascii.Error, ValueError) as error:
            raise InvalidInput('source.imageBase64 is not valid base64', code='bad-source-data') from error
        if not data or len(data) > 20 * 1024 * 1024:
            raise InvalidInput('source image must be 1 byte to 20 MB', code='bad-source-size')
        out: dict[str, Any] = {'id': design_id, 'baseRev': current}
        if not self.recognizers:
            return {**out, 'status': 'unavailable', 'message': 'No recognizer is configured'}
        name = recognition.choose_recognizer(list(self.recognizers), recognizer, self.config.default_recognizer)
        if name is None or name not in self.recognizers:
            raise InvalidInput(f"recognizer must be one of: {', '.join(self.recognizers)}", code='unknown-recognizer')
        inp = recognition.RecognitionInput(kind=kind, data=data, name=str(source.get('name') or ''), media_type=str(source.get('mediaType') or ''),
                                      note=recognition.recognizer_wire.clean_note(source.get('note')))
        anchor, mode = self._check_anchor(anchor, mode)
        return self._recognition_result(design_id, spec, current, out, name, lambda: self.recognizers[name].recognize(inp), country, anchor, mode)

    def recognize_collect(self, design_id: str, job: str, base_revision: int | None=None, country: str | None=None, anchor: dict[str, Any] | None=None,
                          mode: str='add') -> dict:
        """Ask again for a recognition that came back ``pending`` (recognizer ``inbox``: someone answers the job's questions by chat first).

        The answer is that of :meth:`recognize`: still ``pending`` while questions are open, then ``ok`` / ``empty`` / ``failed``.
        """
        spec, current = self.store.get(design_id)
        if base_revision is not None and base_revision != current:
            raise ConflictError(f'base_rev={base_revision}, but the latest revision is {current}; reload before editing')
        job_id = recognition.recognizer_wire.clean_job_id(job)
        if not job_id:
            raise InvalidInput('job is not a recognition job id', code='bad-job')
        out: dict[str, Any] = {'id': design_id, 'baseRev': current}
        inbox = self.recognizers.get('inbox')
        if inbox is None:
            return {**out, 'status': 'unavailable', 'message': 'The inbox recognizer is not configured (CABINET_RECOGNIZER_URL)'}
        anchor, mode = self._check_anchor(anchor, mode)
        return self._recognition_result(design_id, spec, current, out, 'inbox', lambda: inbox.collect(job_id), country, anchor, mode)

    @staticmethod
    def _check_anchor(anchor: Any, mode: Any) -> tuple[dict[str, Any] | None, str]:
        if mode not in ('add', 'replace'):
            raise InvalidInput("mode must be 'add' or 'replace'", code='bad-mode')
        if anchor is None:
            return None, mode
        point = anchor.get('point') if isinstance(anchor, dict) else None
        if not (isinstance(anchor, dict) and isinstance(anchor.get('structureId'), str) and isinstance(point, dict)
                and all(isinstance(point.get(k), (int, float)) and not isinstance(point.get(k), bool) for k in ('x', 'z'))):
            raise InvalidInput('anchor needs structureId and point {x, z} (mm, room frame)', code='bad-anchor')
        return anchor, mode

    def _recognition_result(self, design_id: str, spec: Any, current: int, out: dict[str, Any], name: str, produce: Callable[[], dict],
                            country: str | None, anchor: dict[str, Any] | None=None, mode: str='add') -> dict:
        try:
            raw = produce()
        except recognition.Deferred as waiting:
            return {**out, 'status': 'pending', 'recognizer': name, 'job': waiting.job, 'step': waiting.step,
                    'message': f'Waiting for the answer to step {waiting.step or "?"} of job {waiting.job}'}
        except Exception as error:  # a plug-in may raise anything; the caller gets a status, not a crash
            return {**out, 'status': 'failed', 'recognizer': name, 'message': f'{type(error).__name__}: {error}'[:300]}
        draft = recognition.build_draft(raw)
        if not draft.modules:
            return {**out, 'status': 'empty', 'recognizer': name, 'draft': draft.to_data()}
        layout = recognition.build_layout(raw.get('layout')) if isinstance(raw, dict) else None
        if layout is None:                          # a flat draft (wall + fromCorner): the same kitchen written by runs
            layout = recognition.build_layout(recognition.runs_from_draft(draft, to_data(spec)['common']))
        if layout is None:
            return {**out, 'status': 'empty', 'recognizer': name, 'draft': draft.to_data(), 'message': 'No cabinet could be placed in a run'}
        return self._place_layout(design_id, spec, current, out, name, draft, layout, country, anchor, mode)

    def _place_layout(self, design_id: str, spec: Any, current: int, out: dict[str, Any], name: str, draft: Any, layout: Any, country: str | None,
                      anchor: dict[str, Any] | None, mode: str) -> dict:
        """A kitchen recognised BY RUNS: its main run along the edge the user picked (no edge picked: along the back wall of the kitchen frame,
        instead of the cabinets already there), the runs joined to it square to it."""
        runs = [{'id': r.id, 'length': r.length, 'modules': list(r.modules)} for r in layout.runs]
        joints = list(layout.joints)
        place: dict[str, Any] = {}
        if anchor is None:
            mode = 'replace'
        before: list[dict[str, Any]] = []
        base = spec
        if mode == 'replace':                       # the kitchen that was seen takes the place of this one: its levels, ceiling and materials too
            changes = recognition.common_changes(to_data(spec)['common'], layout, draft.ceiling, dict(draft.materials))
            if changes:
                before = [{'op': 'common', 'changes': changes}]
                base = edit.apply_op(spec, before[0])
        clear = [m.id for m in spec.module] if mode == 'replace' else None
        if anchor is None:
            plan = run_line.plan_runs(base, run_line.back_wall_line(base, runs), runs, joints, clear)
        else:
            struct, plan = self._plan_at_object(base, anchor['structureId'], anchor['point'],
                                                lambda outline, click, system: run_line.plan_runs(base, run_line.edge_line(outline, click), runs, joints, clear, system))
            place = {'structureId': struct['id']}
        if before:
            plan = {**plan, 'operation': edit.combine_ops([*before, plan['operation']])}
        left_out = len(draft.modules) - layout.count
        summary = [*plan['summary'], *layout.notes]
        if layout.rejected or left_out > 0:
            summary.append(f'{max(len(layout.rejected), left_out)} recognised cabinets could not be used')
        preview = self.propose(design_id, plan['operation'], current, None, country)
        return {**out, 'status': 'ok', 'recognizer': name, 'draft': draft.to_data(), 'layout': layout.to_data(), 'operation': plan['operation'],
                'summary': summary, **place, 'mode': mode, 'runs': plan['runs'], 'proposal': preview}

    def propose(self, design_id: str, operation: dict[str, Any], base_revision: int | None=None, scope: list[str] | None=None,
                country: str | None=None) -> dict:
        """Preview an operation without saving: the change list, the validation issues it introduces or resolves, and the modules it touches.

        Confirm by sending the same ``operation`` to :meth:`apply` with the returned ``baseRev``. A stale ``base_revision`` raises
        ConflictError; an operation that cannot be applied (unknown module, bad value) is reported as ``applicable: False``.
        ``scope`` (module ids the user pointed at): modules changed beyond it are listed in ``outsideScope``.
        """
        from pydantic import ValidationError
        from . import proposal
        spec, current = self.store.get(design_id)
        if base_revision is not None and base_revision != current:
            raise ConflictError(f'base_rev={base_revision}, but the latest revision is {current}; reload before editing')
        base = {'id': design_id, 'baseRev': current, 'operation': operation, 'opHash': proposal.op_hash(operation, current)}
        try:
            updated = edit.apply_op(spec.model_copy(deep=True), operation)
        except ValidationError as error:
            msg = '; '.join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors()[:5])
            return {**base, 'applicable': False, 'error': {'type': 'invalid-data', 'message': msg}}
        except (KeyError, ValueError, TypeError) as error:
            return {**base, 'applicable': False, 'error': {'type': 'rejected', 'message': str(error).strip('\'"')}}
        diff = proposal.spec_diff(spec, updated)
        touched = proposal.affected_modules(diff)
        before, after = self.validate_spec(spec, country), self.validate_spec(updated, country)
        out = {**base, 'applicable': True, 'name': updated.name, 'moduleCount': {'before': len(spec.module), 'after': len(updated.module)},
               'diff': diff, 'affectedModules': touched, 'validation': proposal.validation_delta(before, after),
               'unchanged': not touched and not diff['other']}
        if scope is not None:
            out['outsideScope'] = [m for m in touched if m not in set(scope)]
        return out

    def revert(self, design_id: str, target_revision: int, base_revision: int | None) -> dict:
        """Restore an earlier specification by appending a new revision."""
        old_spec, _ = self.store.get(design_id, target_revision)
        operation = {'op': 'replace', 'spec': dump_spec(old_spec), 'fromRev': target_revision}
        return self.apply(design_id, operation, base_revision, 'revert')

    def set_moldings(self, design_id: str, base_revision: int | None, crown: bool=True, base: bool=True, crown_profile: str='classic-crown-layered',
                     base_profile: str='classic-base', style: str | None='Classic', open_end: str='return-to-wall', source: str='') -> dict:
        """Enable or disable the crown and base moldings with the chosen profiles."""
        from .moldings import default_moldings
        moldings = [m.model_dump() | {'openEnd': open_end} for m in default_moldings(crown, base, crown_profile, base_profile)]
        return self.apply(design_id, {'op': 'set-moldings', 'moldings': moldings, 'style': style}, base_revision, source)

    def export_threejs_file(self, design_id: str, revision: int | None=None, country: str | None=None, include_document: bool=False) -> dict:
        """Build the Three.js document, validate it against the schema, write it beside the renders and describe it."""
        import jsonschema
        doc = self.threejs(design_id, revision, country)
        schema = json.loads((Path(__file__).resolve().parents[1] / 'schemas' / 'kitchen-threejs.schema.json').read_text(encoding='utf-8'))
        errors = [error.message for error in jsonschema.Draft202012Validator(schema).iter_errors(doc)][:5]
        out_dir = self.render_dir / design_id / f"rev{doc['metadata']['revision']}"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / 'scene.threejs.json'
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding='utf-8')
        res = {'file': str(path), 'schemaValid': not errors, 'schemaErrors': errors,
               'dem': {kind: len(doc[kind]) for kind in ('modules', 'appliances', 'accessories', 'materials', 'lighting', 'cameras')},
               'partCount': sum(len(m['parts']) + len(m['doors']) + len(m['drawers']) for m in doc['modules'])}
        if include_document:
            res['doc'] = doc
        return res

    def history(self, design_id: str) -> list[dict]:
        """Return the revision history for a design."""
        return self.store.history(design_id)

    def list_designs(self) -> list[dict]:
        """List stored designs and their latest revisions."""
        return self.store.list_designs()

    def validate_spec(self, spec: KitchenSpec, country: str | None=None, region: str | None=None, **legacy: Any) -> dict:
        """Validate a specification against geometry and stored knowledge rules."""
        country = legacy.pop('country', country)
        region = legacy.pop('region', region)
        if legacy:
            raise TypeError(f"Unexpected options: {', '.join(legacy)}")
        return rules.validate(spec, self.store.rule_rows(), country, region)

    def validate(self, design_id: str, revision: int | None=None, country: str | None=None, region: str | None=None, **legacy: Any) -> dict:
        """Validate a stored revision using its default or overridden jurisdiction."""
        country = legacy.pop('country', country)
        region = legacy.pop('region', region)
        if legacy:
            raise TypeError(f"Unexpected options: {', '.join(legacy)}")
        spec, stored_revision = self.store.get(design_id, revision)
        return {'id': design_id, 'rev': stored_revision, **self.validate_spec(spec, country, region)}

    def scene(self, design_id: str, revision: int | None=None) -> dict:
        """Compile a design revision into the basic geometry scene."""
        spec, stored_revision = self.store.get(design_id, revision)
        return {'id': design_id, 'rev': stored_revision, **geometry.scene_json(spec)}

    def threejs(self, design_id: str, revision: int | None=None, country: str | None=None, **legacy: Any) -> dict:
        """Export a scene document using the Complete Kitchen Three.js schema."""
        country = legacy.pop('country', country)
        if legacy:
            raise TypeError(f"Unexpected options: {', '.join(legacy)}")
        spec, stored_revision = self.store.get(design_id, revision)
        return threejs_export.export(spec, design_id, stored_revision, self.store.rule_rows(), country, self.clock())

    def render(self, design_id: str, revision: int | None=None, views: list[str] | None=None, width: int=1280, height: int=960) -> dict:
        """Render control images for selected views and persist them by revision."""
        if not (256 <= width <= 4096 and 256 <= height <= 4096):
            raise InvalidInput('Width and height must be between 256 and 4096.')
        spec, stored_revision = self.store.get(design_id, revision)
        output_dir = self.render_dir / design_id / f'rev{stored_revision}'
        result = render.render_views(spec, output_dir, views, width, height, meta={'designId': design_id, 'rev': stored_revision})
        return {'id': design_id, 'rev': stored_revision, **result}

    def ai_export(self, design_id: str, revision: int | None=None, views: list[str] | None=None, country: str | None=None, with_images: bool=False, embed: bool=False, lighting: str='daylight', **legacy: Any) -> dict:
        """Build an AI image-generation package for a design revision."""
        country = legacy.pop('country', country)
        lighting = legacy.pop('lighting', lighting)
        if legacy:
            raise TypeError(f"Unexpected options: {', '.join(legacy)}")
        from . import ai_export
        return ai_export.build(self, design_id, revision, views, country, with_images, embed, lighting)

    def image_backends(self) -> dict:
        """Image backends, geometry-edit operations and lighting presets the UI can offer."""
        from . import backends, geometry_edit, prompts
        return {'backends': backends.BACKENDS, 'operation': geometry_edit.OPERATIONS,
                'lighting': prompts.LIGHTING_VI, 'default': self.config.default_backend}

    def check_request(self, text: str) -> dict:
        """Check a pasted customer request for contradictions and gaps before designing."""
        from . import request_check
        return request_check.check_text(text)

    def search_knowledge(self, query: str='', kinds: list[str] | None=None, country: str | None=None, region: str | None=None, region_only: bool=False, **legacy: Any) -> list[dict]:
        """Search knowledge entries with optional country and region prioritization."""
        country = legacy.pop('country', country)
        region = legacy.pop('region', region)
        region_only = legacy.pop('region_only', region_only)
        if legacy:
            raise TypeError(f"Unexpected options: {', '.join(legacy)}")
        return self.store.knowledge(query, kinds, country, region, region_only)

    def molding_profiles(self, design_id: str | None=None) -> dict:
        """Return built-in molding profiles plus profiles defined by a design."""
        from . import moldings
        profiles = dict(moldings.PRESETS)
        if design_id:
            spec, _ = self.store.get(design_id)
            profiles.update({profile.id: profile for profile in spec.moldingProfiles})
        return {key: {'id': profile.id, 'name': profile.name, 'description': profile.description, 'variant': 'base' if 'base' in key else 'crown', 'height': profile.height, 'overhang': profile.overhang, 'points': profile.points} for key, profile in profiles.items()}

    def list_regions(self) -> dict:
        """Return supported regions, countries, and knowledge-entry counts."""
        return {'region': regions.REGIONS, 'country': {code: {'name': data[0], 'region': data[1]} for code, data in regions.COUNTRIES.items()}, 'entryCounts': self.store.regions_summary()}

    def add_knowledge(self, **kwargs) -> dict:
        """Insert or update a knowledge entry."""
        return self.store.upsert_knowledge(**kwargs)
