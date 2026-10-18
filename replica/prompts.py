"""Prompts. The agent and the baseline get the same reference card and target pictures; only the actions differ.
The checker prompts never mention a score: the checker describes differences, it does not grade."""

COMMON = '''You are reproducing a short motion-graphics animation.
The attached image shows 12 evenly spaced frames of the TARGET animation (time in seconds above each row of 4).
Composition: {w}x{h} px, {fr} fps, frames {ip}..{op_last} ({frames} frames, {duration:.3f} s), white background.
Your result is rendered in Adobe After Effects and compared pixel by pixel with the target at every frame,
so match shapes, colours, positions, sizes, layering, and timing/easing as closely as you can.
Use your budget to get as close as possible; finish only when you cannot improve the result further.
'''

LOTTIE_CARD = '''## Format: Lottie JSON (subset that compiles exactly to After Effects)
Top level: {{"v":"5.9.0","w":{w},"h":{h},"fr":{fr},"ip":{ip},"op":{op},"ddd":0,"assets":[],"layers":[...]}}
Layers: layers[0] is drawn ON TOP. Shape layer:
  {{"ty":4,"ind":1,"ip":0,"op":{op},"st":0,"sr":1,"ks":{{TRANSFORM}},"shapes":[GROUP,...]}}
  ip/op = first/last+1 frame the layer is visible. "ind" must be unique.
TRANSFORM (layer "ks"): "a" anchor [x,y,0], "p" position [x,y,0], "s" scale [%x,%y,100], "r" rotation deg, "o" opacity 0-100.
  Static value: {{"a":0,"k":VALUE}}
  Animated:     {{"a":1,"k":[KEY,...,LAST]}}  times "t" in frames, strictly increasing
    KEY  = {{"t":0,"s":[v...],"o":{{"x":[0.33],"y":[0]}},"i":{{"x":[0.67],"y":[1]}}}}   (cubic-bezier easing of the segment to the next key;
           "o" = first handle, "i" = second handle; x in 0..1; y may exceed 0..1 for overshoot; for multi-dimensional values
           x/y may hold one number per dimension)
    LAST = {{"t":30,"s":[v...]}}     (omit "o"/"i" on any key for linear motion)
    Position keys may add spatial tangents "to" (out, relative to this key) and "ti" (in, relative to the NEXT key) for curved paths.
  Scalar properties ("r","o") still use one-element arrays in keys: "s":[45].
GROUP: {{"ty":"gr","it":[SHAPES..., PAINTS..., GROUP_TRANSFORM]}}  (groups may nest; the transform item comes last)
  Rectangle {{"ty":"rc","p":{{"a":0,"k":[cx,cy]}},"s":{{"a":0,"k":[w,h]}},"r":{{"a":0,"k":corner}}}}
  Ellipse   {{"ty":"el","p":{{"a":0,"k":[cx,cy]}},"s":{{"a":0,"k":[w,h]}}}}
  Path      {{"ty":"sh","ks":{{"a":0,"k":{{"c":true,"v":[[x,y],...],"i":[[dx,dy],...],"o":[[dx,dy],...]}}}}}}  (i/o tangents relative to each vertex; c=false for open paths)
  Fill      {{"ty":"fl","c":{{"a":0,"k":[r,g,b,1]}},"o":{{"a":0,"k":100}},"r":1}}   colours 0..1; r: 1 nonzero, 2 even-odd
  Stroke    {{"ty":"st","c":{{"a":0,"k":[r,g,b,1]}},"o":{{"a":0,"k":100}},"w":{{"a":0,"k":width}},"lc":2,"lj":2,"ml":4}}  lc/lj 1 butt|miter, 2 round, 3 square|bevel
  GROUP_TRANSFORM {{"ty":"tr","p":{{"a":0,"k":[0,0]}},"a":{{"a":0,"k":[0,0]}},"s":{{"a":0,"k":[100,100]}},"r":{{"a":0,"k":0}},"o":{{"a":0,"k":100}}}}
  Paints apply to the shapes listed before them in the same group. Everything inside "shapes" (including group
  transforms) is static; animate with the LAYER transform "ks" only (use one layer per independently moving part).
Not supported (rejected): parenting, effects, trim paths, gradients, dashes, text, images, blend modes, expressions, hold keys, skew.
'''

REFERENCE_PICTURES = '''## More pictures of the target
After the overview come filmstrip image(s) of the target at {cells} evenly spaced times (time above each cell), and a
motion-curve chart: for each main colour of the target, its visible size and the x / y of its centre over time (a gap
means that colour is not visible then). Use them for timing, order and easing; white parts are not in the curves.
'''

LOOP_ACTIONS = '''## Actions (reply with exactly ONE JSON object per message; anything outside the JSON is ignored)
{{"action":"set_ir","ir":{{...complete Lottie JSON...}}}}      replace your animation (validated; errors explain what to fix)
{{"action":"patch_ir","ops":[{{"op":"replace","path":"/layers/0/ks/p/k/1/s","value":[120,80,0]}}]}}
     edit with JSON Patch (op: add | remove | replace; path is a JSON Pointer into your current IR)
{{"action":"get_ir"}}                                          return your current IR
{{"action":"preview","times":[0.5,1.0]}}                       up to 6 times (s): image rows = target | yours | difference heat map
{{"action":"review"}}                                          an independent reviewer compares the whole animation over time
                                                              (filmstrips and motion curves of target vs yours) and lists the
                                                              differences that matter most, including timing and easing
{{"action":"finish"}}                                          deliver your current IR (it is then compiled into After Effects)
After every accepted set_ir/patch_ir a reviewer automatically gives a quick check (better/worse than your previous
version, biggest differences); it is not counted as an action. Work in small steps: set_ir for the first version or a
real rewrite, patch_ir for corrections, and read each quick check before the next change. Use review for a full
look at timing (it may zoom into frames), especially before you finish. From action 12 on, if you have not had a
full review yet, the next accepted change gets one automatically instead of the quick check; the same happens once more
near the end. Fix what a review lists with patch_ir rather than rewriting everything.
Previews are fast (milliseconds); checks and reviews take a minute or more. Budget: {steps} actions, {minutes} minutes. Start with set_ir.
'''

ONESHOT_ACTIONS = '''## Answer
Reply with exactly ONE JSON object: {{"action":"submit","ir":{{...complete Lottie JSON...}}}}
You get one attempt and no feedback. It is compiled into After Effects as-is.
'''


# ---- checker (a separate session of the same model; sees pictures only) ----

REVIEWER = '''You are an animation reviewer. Someone is reproducing a TARGET motion-graphics animation; compare their
current version ("yours") with the target. Canvas {w}x{h} px, {fr} fps, {duration:.2f} s, white background.
Images: {strips} filmstrip image(s) with a "target" row and a "yours" row at the same times (time above each cell),
then a motion-curve chart: for each main colour of the target, its visible size and the x / y of its centre over time;
thick coloured line = target, thin black line = yours, a gap = that colour is not visible. White parts are not in the
curves; check them in the filmstrips.

List the visible differences that matter most, most important first, at most 8. For each: which element (colour,
shape, where), the time range, what is wrong (missing, extra, wrong shape, position, size, colour, layering, appears or
disappears early/late, moves too fast/slow, wrong easing, missing bounce or overshoot) and what the target does instead.
Use canvas pixels (x right, y down) and seconds. Do not grade or score anything.
Optional, at most once: if you need every frame of a short stretch to judge timing, reply ONLY with {{"zoom":[start_s,end_s]}}
(at most 1 s long) and you will get those frames; then give your list.
End with exactly one line: REMAINING: yes (some clearly visible difference is left) or REMAINING: no.
'''

REVIEW_ZOOM_REPLY = ('Every frame of the stretch you asked for (target row above yours). Now give your list of differences, '
                     'ending with the line REMAINING: yes or REMAINING: no.')


QUICK = '''You are an animation reviewer. Someone is reproducing a TARGET motion-graphics animation. Canvas {w}x{h} px,
{fr} fps, {duration:.2f} s, white background. The image is a filmstrip at the same times (time above each cell) with rows:
{rows}.
{ask}Then list the 3 biggest remaining differences between "yours" and the target (element, time range, what is wrong,
what the target does instead; canvas pixels x right / y down, seconds). At most 8 short lines in total. Do not score.
'''


QUICK = '''You are an animation reviewer. Someone is reproducing a TARGET motion-graphics animation. Canvas {w}x{h} px,
{fr} fps, {duration:.2f} s, white background. The image is a filmstrip at the same times (time above each cell) with rows:
{rows}.
{ask}Then list the 3 biggest remaining differences between "yours" and the target (element, time range, what is wrong,
what the target does instead; canvas pixels x right / y down, seconds). At most 8 short lines in total. Do not score.
'''


def quick_prompt(task, with_previous):
    rows = '"target", "previous" (their last version), "yours" (their new version)' if with_previous else '"target", "yours"'
    ask = ('First say whether "yours" is closer to the target than "previous", about the same, or further away, and which '
           'parts got better or worse; end that first line with CHANGE: better, CHANGE: same or CHANGE: worse.\n'
           if with_previous else '')
    return QUICK.format(**task, rows=rows, ask=ask)


def cells(task):
    return min(task['frames'], 48)


def reviewer_prompt(task, strips):
    return REVIEWER.format(**task, strips=strips)


def opening(condition, task, steps, minutes):
    fmt = dict(task, op_last=task['op'] - 1, steps=steps, minutes=minutes)
    actions = {'loop': LOOP_ACTIONS, 'oneshot': ONESHOT_ACTIONS}[condition]
    return (COMMON.format(**fmt) + REFERENCE_PICTURES.format(cells=cells(task)) + LOTTIE_CARD.format(**fmt)
            + actions.format(**fmt))
