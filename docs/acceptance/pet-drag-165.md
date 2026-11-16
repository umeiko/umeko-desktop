# Desktop pet drag regression (#165)

Base: upstream main `1bd8cb98fa8a62cf3164156960e6306a81e12a45`.

The input now lives in a non-modal tool window, with the existing PidPopup
rendered as an item inside it. This keeps the capsule appearance, PID animation,
Escape dismissal, binding and task dispatch, without native popup mouse grabs.
Clicking/dragging the pet keeps the draft open. Moving focus to another window
closes the capsule after a short grace period, except during IME composition.
Dragging uses the global cursor displacement from the original press and window
position rather than repeatedly accumulating popup-forwarded local coordinates.

Validation (Linux Qt offscreen, matching prepared Pi runtime):
- 22 desktop-pet and 37 pet unit tests passed.
- `desktop_pet_task_ui_smoke.py`: native Qt focus-window/object and input-method
  enabled checks, synthetic preedit, send/real local Pi roundtrip, failed draft,
  Escape, external-window dismissal, binding loss, edges, fonts, PID animation.
- `desktop_pet_drag_ui_smoke.py`: fixed global cursor sequence +10/+20/+30/+20/0
  moves x=350 to 360/370/380/370/350 with y=250 unchanged, both with and without
  the capsule; open state, draft, companion positioning and persisted position.
- Screenshots in `build/pet-task-ui/drag-composer.png` and `drag-pet.png` are
  real captures of the separate windows, not a combined desktop screenshot.

Windows OS IME candidate selection, multi-monitor mixed-DPI interaction and
native foreground restrictions were not validated. Synthetic QInputMethodEvent
checks are not proof of real OS IME operation. No release or PR published yet.

Follow-up: while the composer is visible, ordinary reaction bubbles are hidden.
Assistant task notices and reminder cards remain enabled; input placement avoids
covering them, using below-notice placement when above-notice space is unavailable
at the screen top. The drag regression asserts per-event companion movement,
open state and draft retention, plus notice non-overlap at normal/top positions.
