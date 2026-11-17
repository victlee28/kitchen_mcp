// Pure logic for the free-command box, the photo/drawing upload and the styleFrom select (no DOM, no fetch).
import { describeProposal } from './menu-logic.js';
import { tx } from './i18n.js';

export const MAX_UPLOAD_BYTES = 12 * 1024 * 1024;
export const UPLOAD_TYPES = ['image/png', 'image/jpeg', 'image/webp'];

/** Options of the styleFrom select: the default (server decides), auto, none, then every other view. */
export function styleFromOptions(views, current) {
  return [{ value: '', label: tx('ui.mac-dinh-gen-0-tu-chon-job') }, { value: 'auto', label: tx('ui.tu-chon-anh-da-duyet-moi-nhat') },
    { value: 'none', label: tx('ui.khong-dung-anh-tham-chieu-phong-cach') },
    ...views.filter((v) => v !== current).map((v) => ({ value: v, label: tx('ui.lay-phong-cach-tu-goc', { 0: v }) }))];
}

/** The value to send as `styleFrom`, or undefined to leave it out. A view that no longer exists falls back to the default. */
export function styleFromValue(value, views, current) {
  if (!value) return undefined;
  if (value === 'auto' || value === 'none') return value;
  return value !== current && views.includes(value) ? value : undefined;
}

export function interpretBody(text, baseRev, { scope, useLlm } = {}) {
  const t = String(text ?? '').trim();
  if (!t) throw new Error(tx('ui.hay-nhap-cau-lenh'));
  const body = { text: t, baseRev };
  if (scope?.length) body.scope = scope;
  if (useLlm) body.useLlm = true;
  return body;
}

/** An /interpret answer as what the UI shows: {kind: 'preview'|'clarify'|'unsupported', ...}. */
export function describeInterpret(r) {
  if (r.status === 'ok' && r.proposal) {
    return { kind: 'preview', summary: r.summary || [], lines: describeProposal(r.proposal), proposal: r.proposal,
      canApply: r.proposal.applicable && !r.proposal.unchanged, introducesErrors: !!r.proposal.validation?.introducesErrors };
  }
  if (r.status === 'clarify') return { kind: 'clarify', question: r.question || '', choices: r.choices || [] };
  return { kind: 'unsupported', message: r.message || tx('ui.chua-hieu-cau-lenh-nay'), llm: r.llm || null };
}

/** The body of POST /ops that confirms exactly the previewed proposal. */
export function confirmBody(proposal) {
  return { op: proposal.operation, baseRev: proposal.baseRev, expect: proposal.opHash };
}

export function checkUpload(file) {
  if (!file) return tx('ui.chua-chon-tep');
  if (!UPLOAD_TYPES.includes(file.type)) return tx('ui.chi-nhan-anh-png-jpeg-hoac-webp');
  if (file.size > MAX_UPLOAD_BYTES) return tx('ui.anh-qua-lon-toi-da-mb', { 0: MAX_UPLOAD_BYTES / 1048576 });
  return null;
}

/** Where a recognised run stands: along the edge of the floor-plan object picked with the right click. null when the target is no such object. */
export function anchorFor(target) {
  const p = target?.point;     // a floorplan element, or a room opening the design places (its id: the server finds it among the openings)
  if (!['structure', 'opening'].includes(target?.kind) || typeof target.id !== 'string' || !p || !Number.isFinite(p.x) || !Number.isFinite(p.z)) return null;
  return { structureId: target.id, point: { x: p.x, z: p.z } };
}

/** The headline of a preview made from a picture of a room opening (mode 'opening'): which opening of the drawing it replaces or
 *  fills, at what size; else the plain warning that it is added to the wall picked. */
export function photoOpeningHeadline(data) {
  const op = data?.operation ?? data?.proposal?.operation;
  const size = (o) => ({ w: Math.round(o?.width ?? 0), h: Math.round(o?.height ?? 0) });
  if (op?.op === 'update-opening') return tx('ui.opening.from-photo-replace', { id: op.id, ...size(op.changes) });
  if (op?.op === 'add-opening' && op.opening?.sourceElement) return tx('ui.opening.from-photo-hole', { id: op.opening.sourceElement, ...size(op.opening) });
  return tx('ui.opening.from-photo');
}

const place = (anchor, mode) => ({ ...(anchor ? { anchor } : {}), ...(mode === 'replace' ? { mode } : {}) });

export function recognizeBody(kind, name, mediaType, base64, baseRev, note = '', anchor = null, mode = 'add', openingType = null) {
  if (kind !== 'photo' && kind !== 'drawing') throw new Error(tx('ui.kind-phai-la-photo-hoac-drawing'));
  const hint = String(note ?? '').replace(/\s+/g, ' ').trim().slice(0, 500);   // same limit as the server; empty = not sent
  return { source: { kind, name, mediaType, imageBase64: base64, ...(hint ? { note: hint } : {}) }, baseRev, ...place(anchor, mode),
    ...(openingType ? { openingType } : {}) };
}

/** Body of POST .../recognize-job: ask again for the result of a recognition that answered `pending`. */
export function recognizeJobBody(job, baseRev, anchor = null, mode = 'add', openingType = null) {
  const id = String(job ?? '').trim();
  if (!/^\d{8}-\d{6}(-\d+)?$/.test(id)) throw new Error(tx('ui.ma-job-khong-hop-le'));
  return { job: id, baseRev, ...place(anchor, mode), ...(openingType ? { openingType } : {}) };
}

const pct = (c) => `${Math.round((c ?? 1) * 100)}%`;

/** A /recognize answer as {kind: 'preview'|'message', text?, lines, proposal?, ...}. */
export function describeRecognition(r, lang = 'vi') {
  const draft = r.draft;
  const draftLines = draft ? [
    ...draft.modules.map((m) => ({ kind: m.needsReview ? 'warn' : 'info',
      text: tx('ui.tuong-mm', { 0: m.type, 1: m.wall, 2: m.width, 3: m.label ? ` · ${m.label}` : '', 4: pct(m.confidence), 5: m.needsReview ? tx('ui.can-kiem-tra-2') : '' }) })),
    ...draft.rejected.map((x) => ({ kind: 'bad', text: tx('ui.bo-qua-muc', { 0: x.index + 1, 1: x.reason }) })),
    ...draft.notes.map((text) => ({ kind: 'info', text }))] : [];
  switch (r.status) {
    case 'ok': return { kind: 'preview', summary: r.summary || [], lines: [...draftLines, ...describeProposal(r.proposal)], proposal: r.proposal,
      canApply: r.proposal.applicable && !r.proposal.unchanged, introducesErrors: !!r.proposal.validation?.introducesErrors };
    case 'question': return { kind: 'choices', text: tx('ui.opening.pick-type'), lines: draftLines,
      choices: (r.choices || []).map((c) => ({ type: c.openingType, label: c.label?.[lang] || c.label?.vi || c.openingType })) };
    case 'pending': return { kind: 'pending', job: r.job, step: r.step, lines: [],
      text: tx('ui.da-tao-job-hay-nhan-claude-tra', { 0: r.job, 1: r.step ? tx('ui.dang-cho-buoc', { 0: r.step }) : '', 2: r.job }) };
    case 'empty': return { kind: 'message', tone: 'warn', text: tx('ui.khong-nhan-ra-tu-nao-trong-anh'), lines: draftLines };
    case 'unavailable': return { kind: 'message', tone: 'warn', text: tx('ui.chua-co-bo-nhan-dien-chay-bang'), lines: [] };
    case 'failed': return { kind: 'message', tone: 'bad', text: tx('ui.bo-nhan-dien-loi', { 0: r.message || tx('ui.khong-ro') }), lines: [] };
    default: return { kind: 'message', tone: 'warn', text: tx('ui.trang-thai-la', { 0: r.status }), lines: [] };
  }
}

const plain = (t) => String(t ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/gi, 'd').toLowerCase();

/**
 * Does the sentence ask for a cabinet template ("tạo cho tôi tủ chữ I ở đây", "làm dãy tủ dọc cạnh này")?
 * -> {kind: 'run-i'} | {kind: 'shape', shape: 'L'|'U'} (not built from a sentence yet) | null.
 */
export function templateIntent(text) {
  const f = plain(text);
  if (!/\b(tao|lam|dung|ve|dat|them|xep|cho|can|thiet\s+ke|xay|lap|thay)\b/.test(f)) return null;
  const shape = /\b(?:tu\s+)?(?:bep\s+)?chu\s+([lu])\b/.exec(f);
  if (shape) return { kind: 'shape', shape: shape[1].toUpperCase() };
  if (/\b(?:tu\s+)?(?:bep\s+)?chu\s+i\b|\bday\s+tu\b|\btu\s+doc\b/.test(f)) return { kind: 'run-i' };
  // A described kitchen ("tạo tủ bếp có tủ lạnh, mặt đá đen"): only with a clear "make it" verb, so edit sentences ("cánh kính cho tủ trên") stay edits.
  if (/\b(tao|lam|dung|thiet\s+ke|xay|lap|ve|dat|xep|thay)\b/.test(f) && /\btu\s+bep\b|\btu\s+lanh\b|\bmat\s+da\b|\btu\s+(duoi|tren|nong|noc)\b|\bday\s+tu\b|\bhe\s+tu\b|\b(?:tu|ke|vach)\s+(?:ti\s*vi|tv)\b/.test(f)) return { kind: 'run-i', described: true };
  return null;
}

/** Might the sentence be about a room door, a room opening or a passage, or ask to save what was clicked ("lưu vào database")? A cheap first look:
 *  the server reads it (/opening-command) and answers 'not-opening' when it is about something else ("đổi màu cửa tủ"). */
export function opensOrSaves(text) {
  const f = plain(text);
  return /\bcua\b|\bluu\b|\bdoor\b|\bwind[o]w\b|\bsave\b|\bloi di\b/.test(f);
}

/** "nối góc", "nối dãy", "join the runs": two runs that meet at a corner (any angle) joined there (/template kind 'join-runs'). */
export function joinsRuns(text) {
  const f = plain(text);
  return /\bnoi (goc|day|hai day|2 day|voi day)\b|\bjoin\b/.test(f);
}

/** "thay (thế) … bằng cửa đi": on cabinets the browser itself takes them out and puts the door in their place (menu-logic openingCommand). */
export function replacesWithDoor(text) {
  const f = plain(text);
  return /\b(thay the|thay|replace)\b/.test(f) && /\bcua di\b|\bcua ra vao\b/.test(f);
}

/** A sentence about the clicked cabinet's whole SYSTEM ("thay cả hệ tủ …", "sửa lại, thêm tủ nóc cho hệ, cho tủ lạnh sang phải"): it names the
 *  system ("hệ tủ", "cả / cho / của / toàn hệ") and asks for a change (thay, đổi, sửa, làm lại, thêm, bỏ…). Returns null when it is not such a
 *  sentence, else `{ prompt }` (what is left once the system phrase and the lead-in verbs are taken out describes the new system: it is laid out
 *  again) or `{ style }` (nothing is left, "phong cách khác", or the name of a preset: the cabinets stay and take that style; `auto` = one unlike
 *  the current). `styles`: the catalog's style presets, [{ id, names: [vi, en] }], so a preset can be named in the sentence. */
export function systemIntent(text, styles = []) {
  const words = String(text ?? '').trim().split(/\s+/).filter(Boolean);
  const flat = words.map((w) => plain(w).replace(/^[^a-z0-9]+|[^a-z0-9]+$/g, ''));
  const f = flat.join(' ');
  if (!/\bhe\s+tu\b|\bhe\s+(?:tivi|tv)\b|\b(ca|cho|cua|toan|nguyen)\s+he\b/.test(f)) return null;
  if (!/\b(thay|doi|chuyen|sua|lam\s+lai|xep\s+lai|tao\s+lai|them|bo|bot)\b/.test(f)) return null;
  // take out the system phrase: [cả / cho / của / toàn / nguyên] hệ [tủ] [này / hiện tại / cũ / đang có / đó]
  const at = flat.findIndex((w, k) => w === 'he' && (['tu', 'tivi', 'tv'].includes(flat[k + 1]) || ['ca', 'cho', 'cua', 'toan', 'nguyen'].includes(flat[k - 1])));
  if (at < 0) return null;
  let from = at;
  while (from > 0 && ['ca', 'cho', 'cua', 'toan', 'nguyen'].includes(flat[from - 1])) from -= 1;     // "cho cả hệ", "của toàn hệ"…
  let to = at + (flat[at + 1] === 'tu' ? 2 : 1);
  while (to < flat.length && ['nay', 'hien', 'tai', 'cu', 'dang', 'co', 'do'].includes(flat[to]) && !(flat[to] === 'co' && flat[to - 1] !== 'dang')) to += 1;
  if (words[to - 1] && /[,;:.]$/.test(words[to - 1]) && from > 0) words[from - 1] = words[from - 1].replace(/[,;:.]?$/, ',');
  const keep = [...words.slice(0, from), ...words.slice(to)]; const kflat = [...flat.slice(0, from), ...flat.slice(to)];
  // then the lead-in: [thay / đổi / sửa / làm / xếp / tạo / chuyển] [lại / thế] [bằng / sang / thành / theo / với / qua] [một] [hệ] [tủ] [mới / khác]
  let i = 0;
  const skip = (set) => { while (i < kflat.length && (set.includes(kflat[i]) || kflat[i] === '')) i += 1; };
  skip(['thay', 'doi', 'sua', 'lam', 'xep', 'tao', 'chuyen']); skip(['lai', 'the']);
  skip(['bang', 'sang', 'thanh', 'theo', 'voi', 'qua']); skip(['mot', '1']);
  if (kflat[i] === 'he') { i += 1; if (kflat[i] === 'tu') i += 1; skip(['moi', 'khac']); }     // "… bằng một hệ tủ mới": not "tủ lạnh"

  const rest = keep.slice(i).join(' ').replace(/\s+([,;:.])/g, '$1').replace(/([,;:])(?=[,;:.])/g, '').replace(/^[:,;.\s-]+|[,;:\s]+$/g, '').trim();
  const r = plain(rest).replace(/[.!]+$/, '').trim();
  if (!r || /^(phong\s+cach|kieu|style)(\s+(khac|moi))?$/.test(r) || /^(mot\s+)?(phong\s+cach|kieu)\s+khac(\s+di)?$/.test(r)) return { style: 'auto' };
  const named = styles.find(({ id, names }) => names.some((n) => r === plain(n) || r === `phong cach ${plain(n)}`) || r === id);
  return named ? { style: named.id } : { prompt: rest };
}

/** Does the sentence point at a reference picture ("giống hình ảnh tham chiếu", "theo ảnh mẫu")? Such a sentence needs an attached image. */
export function mentionsReference(text) {
  const f = plain(text);
  return /\b(anh|hinh|hinh anh|ban ve)\s+(tham\s+chieu|mau|goc|nay|da\s+chon)\b|\bgiong\s+(voi\s+)?(anh|hinh|ban ve)\b|\btheo\s+(anh|hinh|ban ve)\b/.test(f);
}

/** Lines for a preview from a recognition answer, as [{kind, text}] (draft first). Empty when there is no draft. */
export function recognitionLines(r) {
  const d = describeRecognition(r);
  return d.kind === 'preview' ? d.lines.slice(0, d.lines.length - describeProposal(r.proposal).length) : d.lines;
}

// ---- the command inbox: a right-click sentence sent to Claude (server mode KITCHEN_MENU_COMMANDS=inbox)

/** The wall faces a right-click sentence is about: the faces picked before it (Ctrl / Shift + click) when the click lands on one of
 *  them, or anywhere on a wall that has a picked face (its top, an edge, the wall's own body); none when it lands on anything else. */
export function facesForTarget(target, picked = []) {
  if (!target || !picked?.length) return [];
  if (target.surface) return [...picked];
  if (!['structure', 'surface'].includes(target.kind) || !target.id) return [];
  const wall = String(target.id).replace(/^STRUCT-/, '').split('#')[0];
  return picked.some((f) => String(f).split('#')[0] === wall) ? [...picked] : [];
}

/** What was right-clicked, as the inbox record keeps it (kitchen/menu_commands.clean_place): the target's kind, id, part, point,
 *  floorplan element, module / group, picked wall faces and the menu's heading. */
export function commandPlace(target, title = '', surfaces = []) {
  if (!target) return {};
  const out = { kind: target.kind };
  if (target.id) out.id = String(target.id).replace(/^STRUCT-/, '');
  if (target.part) out.part = target.part;
  if (target.point && Number.isFinite(target.point.x) && Number.isFinite(target.point.z)) out.point = { x: target.point.x, z: target.point.z };
  if (target.kind === 'structure' && target.id) out.structureId = String(target.id).replace(/^STRUCT-/, '');
  const module = ['module', 'part'].includes(target.kind) ? target.id : target.kind === 'group' ? target.group?.modules?.[0] : undefined;
  if (module) out.module = module;
  if (target.kind === 'group' && target.group?.modules?.length) out.modules = target.group.modules.slice(0, 50);
  if (surfaces.length) out.surfaces = surfaces.slice(0, 50);
  if (title) out.title = String(title).slice(0, 120);
  return out;
}

/** The body of POST /api/designs/<id>/command. */
export function commandBody(text, baseRev, place, language) {
  const t = String(text ?? '').trim();
  if (!t) throw new Error(tx('ui.command.empty'));
  return { text: t.slice(0, 500), place, baseRev, lang: language === 'en' ? 'en' : 'vi' };
}

/** Claude's answer as the menu keeps showing it until the user decides: {id, text, reply, status, tone, head, choices, undoTo}. ``undoTo``:
 *  the revision the menu's undo goes back to (the one before the change: ``fromRev``, else the one before ``revision``), only while the
 *  design is still at the revision the change made; null otherwise. ``choices``: what Claude offers to pick instead of typing. */
export function answerCard(c, currentRev) {
  const d = describeCommandAnswer({ ...c, reply: '' }, currentRev);
  const at = c.status === 'done' && Number.isInteger(c.revision) && c.revision === currentRev;
  const back = Number.isInteger(c.fromRev) ? c.fromRev : c.revision - 1;
  return {
    id: c.id, text: c.text, reply: typeof c.reply === 'string' ? c.reply : '', status: c.status, tone: d.tone, head: d.text,
    choices: (Array.isArray(c.choices) ? c.choices : []).filter((x) => typeof x === 'string' && x.trim()).slice(0, 6),
    undoTo: at && back >= 1 && back < c.revision ? back : null,
  };
}

/** The user's answer to one of Claude's answers: a new inbox command that names it (``replyTo``); the server gives it that command's
 *  place and what was said, so Claude reads it in context. */
export function replyBody(text, baseRev, answerId, language) {
  return { ...commandBody(text, baseRev, {}, language), replyTo: answerId };
}

/** The answers kept for the menu: the newest last, at most ``max`` per design, without repeats. */
export function keepAnswers(kept, news, max = 5) {
  const all = [...kept.filter((k) => !news.some((n) => n.id === k.id)), ...news];
  const out = [];
  for (const a of [...all].reverse()) {
    if (out.filter((x) => x.designId === a.designId).length < max) out.unshift(a);
  }
  return out;
}

/** What the menu shows of the inbox for a design: {waiting: [records still with Claude], news: [records answered since the menu last
 *  looked, oldest first]}. ``known``: ids the page sent and has not shown an answer for yet. */
export function inboxNews(commands, known) {
  const mine = new Set(known);
  const waiting = commands.filter((c) => mine.has(c.id) && c.status === 'pending');
  const news = commands.filter((c) => mine.has(c.id) && ['done', 'failed', 'question'].includes(c.status));
  return { waiting, news };
}

/** One answered command as a status line: {text, tone: 'ok'|'warn'|'bad', reload: true when the design changed}. */
export function describeCommandAnswer(c, currentRev) {
  const said = c.reply ? ` ${c.reply}` : '';
  if (c.status === 'done') return { text: tx('ui.command.done', { 0: c.text }) + said, tone: 'ok', reload: Number.isInteger(c.revision) ? c.revision !== currentRev : true };
  if (c.status === 'question') return { text: tx('ui.command.question', { 0: c.text }) + said, tone: 'warn', reload: false };
  return { text: tx('ui.command.failed', { 0: c.text }) + said, tone: 'bad', reload: false };
}
