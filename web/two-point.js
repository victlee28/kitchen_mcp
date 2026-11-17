// Two-point perspective for the 3D view (kitchen/two_point.py does the same for the rendered pictures): an eye-level camera looks level and
// the picture is shifted instead of tilted, so vertical edges stay vertical and the point it aims at stays in the middle. Pure: no DOM.
export const MAX_PITCH_DEG = 30;      // steeper views (plan, overhead) keep their tilt; mirrors two_point.MAX_PITCH_DEG

/** For a camera at `position` aiming at `target` ([x, y, z]) with a vertical field of view `fovDeg` and a picture `height` px high:
 * {look: the level point to look at, offsetY: px the view is offset downward (PerspectiveCamera.setViewOffset)}, or null. */
export function twoPoint(position, target, fovDeg, height, maxPitch = MAX_PITCH_DEG) {
  const dx = target[0] - position[0], dy = target[1] - position[1], dz = target[2] - position[2];
  const flat = Math.hypot(dx, dz);
  if (!(flat > 1e-9) || Math.abs(Math.atan2(dy, flat) * 180 / Math.PI) > maxPitch) return null;
  const focal = (height / 2) / Math.tan((fovDeg * Math.PI / 180) / 2);
  return { look: [position[0] + dx / flat, position[1], position[2] + dz / flat], offsetY: -focal * dy / flat };
}
