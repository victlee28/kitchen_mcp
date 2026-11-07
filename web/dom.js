// The two DOM helpers every web module uses. All text goes through text nodes / textContent (never innerHTML).
export const $ = (id) => document.getElementById(id);

const ATTRIBUTE_KEYS = /^(aria-|data-)|^(role|list)$/;   // these have no (or an unreliable) JS property: set the HTML attribute

/**
 * Create an element. props: `class` -> className, `onclick` -> event listener, `aria-*`/`data-*`/`role`/`list` -> HTML attributes,
 * `undefined` -> skipped, anything else -> assigned as a property (`value`, `checked`, `hidden`, `href`, `textContent`...).
 * children: Nodes are appended as they are, everything else as text.
 */
export function el(tag, props = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined) continue;
    if (k === 'class') n.className = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else if (ATTRIBUTE_KEYS.test(k)) n.setAttribute(k, String(v));
    else n[k] = v;
  }
  for (const c of children) n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return n;
}
