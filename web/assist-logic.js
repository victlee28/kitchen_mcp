// Pure logic for the free-command box, the photo/drawing upload and the styleFrom select (no DOM, no fetch).
import { describeProposal } from './menu-logic.js';

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

export function recognizeBody(kind, name, mediaType, base64, baseRev) {
  if (kind !== 'photo' && kind !== 'drawing') throw new Error('kind phải là photo hoặc drawing');
  return { source: { kind, name, mediaType, imageBase64: base64 }, baseRev };
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
    case 'empty': return { kind: 'message', tone: 'warn', text: 'Không nhận ra tủ nào trong ảnh.', lines: draftLines };
    case 'unavailable': return { kind: 'message', tone: 'warn', text: 'Chưa có bộ nhận diện: đặt GEMINI_API_KEY (hoặc GEMINI_ENV_FILE) cho máy chủ rồi chạy lại.', lines: [] };
    case 'failed': return { kind: 'message', tone: 'bad', text: `Bộ nhận diện lỗi: ${r.message || 'không rõ'}`, lines: [] };
    default: return { kind: 'message', tone: 'warn', text: `Trạng thái lạ: ${r.status}`, lines: [] };
  }
}
