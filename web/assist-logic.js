// Pure logic for the free-command box, the photo/drawing upload and the styleFrom select (no DOM, no fetch).
import { describeProposal, SYSTEM_STYLES } from './menu-logic.js';

export const MAX_UPLOAD_BYTES = 12 * 1024 * 1024;
export const UPLOAD_TYPES = ['image/png', 'image/jpeg', 'image/webp'];

/** Options of the styleFrom select: the default (server decides), auto, none, then every other view. */
export function styleFromOptions(views, current) {
  return [{ value: '', label: 'Mặc định (gen-0 tự chọn, job sửa không dùng)' }, { value: 'auto', label: 'Tự chọn ảnh đã duyệt mới nhất còn đúng' },
    { value: 'none', label: 'Không dùng ảnh tham chiếu phong cách' },
    ...views.filter((v) => v !== current).map((v) => ({ value: v, label: `Lấy phong cách từ góc “${v}”` }))];
}

/** The value to send as `styleFrom`, or undefined to leave it out. A view that no longer exists falls back to the default. */
export function styleFromValue(value, views, current) {
  if (!value) return undefined;
  if (value === 'auto' || value === 'none') return value;
  return value !== current && views.includes(value) ? value : undefined;
}

export function interpretBody(text, baseRev, { scope, useLlm } = {}) {
  const t = String(text ?? '').trim();
  if (!t) throw new Error('Hãy nhập câu lệnh');
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
  return { kind: 'unsupported', message: r.message || 'Chưa hiểu câu lệnh này', llm: r.llm || null };
}

/** The body of POST /ops that confirms exactly the previewed proposal. */
export function confirmBody(proposal) {
  return { op: proposal.operation, baseRev: proposal.baseRev, expect: proposal.opHash };
}

export function checkUpload(file) {
  if (!file) return 'Chưa chọn tệp';
  if (!UPLOAD_TYPES.includes(file.type)) return 'Chỉ nhận ảnh PNG, JPEG hoặc WebP';
  if (file.size > MAX_UPLOAD_BYTES) return `Ảnh quá lớn (tối đa ${MAX_UPLOAD_BYTES / 1048576} MB)`;
  return null;
}

/** Where a recognised run stands: along the edge of the floor-plan object picked with the right click. null when the target is no such object. */
export function anchorFor(target) {
  const p = target?.point;
  if (target?.kind !== 'structure' || typeof target.id !== 'string' || !p || !Number.isFinite(p.x) || !Number.isFinite(p.z)) return null;
  return { structureId: target.id, point: { x: p.x, z: p.z } };
}

const place = (anchor, mode) => ({ ...(anchor ? { anchor } : {}), ...(mode === 'replace' ? { mode } : {}) });

export function recognizeBody(kind, name, mediaType, base64, baseRev, note = '', anchor = null, mode = 'add') {
  if (kind !== 'photo' && kind !== 'drawing') throw new Error('kind phải là photo hoặc drawing');
  const hint = String(note ?? '').replace(/\s+/g, ' ').trim().slice(0, 500);   // same limit as the server; empty = not sent
  return { source: { kind, name, mediaType, imageBase64: base64, ...(hint ? { note: hint } : {}) }, baseRev, ...place(anchor, mode) };
}

/** Body of POST .../recognize-job: ask again for the result of a recognition that answered `pending`. */
export function recognizeJobBody(job, baseRev, anchor = null, mode = 'add') {
  const id = String(job ?? '').trim();
  if (!/^\d{8}-\d{6}(-\d+)?$/.test(id)) throw new Error('Mã job không hợp lệ');
  return { job: id, baseRev, ...place(anchor, mode) };
}

const pct = (c) => `${Math.round((c ?? 1) * 100)}%`;

/** A /recognize answer as {kind: 'preview'|'message', text?, lines, proposal?, ...}. */
export function describeRecognition(r) {
  const draft = r.draft;
  const draftLines = draft ? [
    ...draft.modules.map((m) => ({ kind: m.needsReview ? 'warn' : 'info',
      text: `${m.type} · tường ${m.wall} · ${m.width} mm${m.label ? ` · ${m.label}` : ''} (${pct(m.confidence)}${m.needsReview ? ', cần kiểm tra' : ''})` })),
    ...draft.rejected.map((x) => ({ kind: 'bad', text: `Bỏ qua mục ${x.index + 1}: ${x.reason}` })),
    ...draft.notes.map((text) => ({ kind: 'info', text }))] : [];
  switch (r.status) {
    case 'ok': return { kind: 'preview', summary: r.summary || [], lines: [...draftLines, ...describeProposal(r.proposal)], proposal: r.proposal,
      canApply: r.proposal.applicable && !r.proposal.unchanged, introducesErrors: !!r.proposal.validation?.introducesErrors };
    case 'pending': return { kind: 'pending', job: r.job, step: r.step, lines: [],
      text: `Đã tạo job ${r.job}${r.step ? ` (đang chờ bước ${r.step})` : ''}. Hãy nhắn Claude: "trả lời hộp thư job ${r.job}"; khi Claude báo xong, bấm "Cập nhật".` };
    case 'empty': return { kind: 'message', tone: 'warn', text: 'Không nhận ra tủ nào trong ảnh.', lines: draftLines };
    case 'unavailable': return { kind: 'message', tone: 'warn', text: 'Chưa có bộ nhận diện: chạy bằng `python run.py` (đặt CABINET_RECOGNIZER_URL) hoặc đặt GEMINI_API_KEY (hoặc GEMINI_ENV_FILE) cho máy chủ rồi chạy lại.', lines: [] };
    case 'failed': return { kind: 'message', tone: 'bad', text: `Bộ nhận diện lỗi: ${r.message || 'không rõ'}`, lines: [] };
    default: return { kind: 'message', tone: 'warn', text: `Trạng thái lạ: ${r.status}`, lines: [] };
  }
}

const plain = (t) => String(t ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/gi, 'd').toLowerCase();

/**
 * Does the sentence ask for a cabinet template ("tạo cho tôi tủ chữ I ở đây", "làm dãy tủ dọc cạnh này")?
 * -> {kind: 'run-i'} | {kind: 'shape', shape: 'L'|'U'} (not built from a sentence yet) | null.
 */
export function templateIntent(text) {
  const f = plain(text);
  if (!/\b(tao|lam|dung|ve|dat|them|xep|cho|can|thiet\s+ke|xay|lap)\b/.test(f)) return null;
  const shape = /\b(?:tu\s+)?(?:bep\s+)?chu\s+([lu])\b/.exec(f);
  if (shape) return { kind: 'shape', shape: shape[1].toUpperCase() };
  if (/\b(?:tu\s+)?(?:bep\s+)?chu\s+i\b|\bday\s+tu\b|\btu\s+doc\b/.test(f)) return { kind: 'run-i' };
  // A described kitchen ("tạo tủ bếp có tủ lạnh, mặt đá đen"): only with a clear "make it" verb, so edit sentences ("cánh kính cho tủ trên") stay edits.
  if (/\b(tao|lam|dung|thiet\s+ke|xay|lap|ve|dat|xep)\b/.test(f) && /\btu\s+bep\b|\btu\s+lanh\b|\bmat\s+da\b|\btu\s+(duoi|tren|nong)\b/.test(f)) return { kind: 'run-i', described: true };
  return null;
}

/** "Thay cả hệ tủ …" typed in the command box: the whole cabinet system of the clicked cabinet is replaced. Returns null when the sentence is
 *  not about the system, else `{ prompt }` (what follows describes the new system: it is laid out again) or `{ style }` (nothing more, "phong
 *  cách khác", or the name of a preset: the cabinets stay and take that style; `auto` = one unlike the current). */
export function systemIntent(text) {
  const words = String(text ?? '').trim().split(/\s+/).filter(Boolean);
  const flat = words.map(plain);
  const f = flat.join(' ');
  if (!/\bhe\s+tu\b|\bca\s+he\b/.test(f) || !/\b(thay|doi|chuyen|lam\s+lai|xep\s+lai|tao\s+lai)\b/.test(f)) return null;
  // drop the lead-in: everything up to "hệ (tủ)" [này / hiện tại / cũ / đang có] [bằng / sang / thành / theo] [một] [hệ (tủ)] [mới] [:]
  let i = flat.findIndex((w, k) => w === 'he' && (flat[k + 1] === 'tu' || flat[k - 1] === 'ca'));
  if (i < 0) return null;
  i += flat[i + 1] === 'tu' ? 2 : 1;
  const skip = (set) => { while (i < flat.length && set.includes(flat[i].replace(/[:,.]$/, ''))) i += 1; };
  skip(['nay', 'hien', 'tai', 'cu', 'dang', 'co', 'do']);
  skip(['bang', 'sang', 'thanh', 'theo', 'voi', 'qua']);
  skip(['mot', '1', 'he', 'tu', 'moi', 'khac']);
  const rest = words.slice(i).join(' ').replace(/^[:,.\s-]+/, '').trim();
  const r = plain(rest).replace(/[.!]+$/, '').trim();
  if (!r || /^(phong\s+cach|kieu|style)(\s+(khac|moi))?$/.test(r) || /^(mot\s+)?(phong\s+cach|kieu)\s+khac(\s+di)?$/.test(r)) return { style: 'auto' };
  const named = SYSTEM_STYLES.find(([id, label]) => id !== 'auto' && (r === plain(label) || r === `phong cach ${plain(label)}` || r === id));
  return named ? { style: named[0] } : { prompt: rest };
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
