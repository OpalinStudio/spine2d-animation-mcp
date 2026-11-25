"""What the assistant needs to know to make GOOD Spine animation with these
tools, not just valid files: the working method, the animation principles
mapped to tool calls, timing numbers, recipes and the review checklist.

Served by `spine_reference` (topics workflow / quality / recipes / checklist),
by the `spine://guide/...` resources and by the MCP prompts.
"""

from __future__ import annotations

SERVER_INSTRUCTIONS = (
    "Spine 4.3 (Essential/Professional) animation toolkit. Skeletons are Spine JSON files on "
    "disk: every editing tool takes `skeleton` (path to the .json), applies one change, "
    "validates against the 4.3 format and saves (an invalid result is rejected and the file is "
    "left untouched). Coordinates are Spine's: y-up, bone-local, rotations in degrees "
    "counter-clockwise; bone timeline values are offsets from the setup pose (scale is a "
    "multiplier).\n"
    "ART RULE: a rig cannot fix bad art. Before rigging, check_art on the parts and fix every "
    "warning (clean_art for hard edges and fragments, redraw the rest); once the skeleton "
    "exists, check_art(skeleton=...) again for the joints. spine_reference(\"art\") says how "
    "the parts must be drawn or generated.\n"
    "QUALITY RULE: never deliver an animation you have not looked at. After every animation "
    "change: (1) analyze_animation and fix its warnings, (2) runtime_render format=\"sheet\" "
    "(the tool returns the picture: look at every pose) and format=\"onion\" with track_bones "
    "to judge arcs and spacing, (3) correct and re-render until it is right. A valid file is "
    "not a good animation.\n"
    "Flow: art (check_art) -> import_psd_to_spine or create_skeleton -> rig (IK on limbs, "
    "physics on hair / cloth / tails, meshes, sliders) -> block the key poses (set_keyframes) "
    "or start from generate_animation -> curves, overlap (offset_keys), exaggeration "
    "(scale_keys) -> analyze_animation + runtime_render -> runtime_validate -> "
    "spine_import_data (.spine project) / export_game_pack. Call spine_reference(\"quality\") "
    "before animating, spine_reference(\"recipes\") for ready-made numbers, "
    "spine_reference(\"checklist\") before delivering."
)

ART = {
    "why": (
        "Most of what reads as 'low quality animation' is decided before the first key: parts "
        "cut out of one finished illustration cannot be posed differently, a hand drawn as one "
        "image cannot bend a finger, a hard-edged mask shimmers when it rotates. Draw (or "
        "generate) the character FOR animation, then check it with check_art."
    ),
    "design for animation": [
        "simple, readable shapes: tube sleeves and legs, mitten-like hands, big head; a cape, "
        "coat or skirt that hides the shoulder and hip joints makes every pose easier",
        "a NEUTRAL base pose: limbs straight, apart from the body and from each other, seen "
        "flat (no foreshortening); a limb drawn bent or pointing at the viewer only works in "
        "that one pose",
        "closed dark outlines on every part: they hide the seam where two parts overlap",
    ],
    "one image per moving part": [
        "limbs in segments: upper arm, forearm, hand; thigh, shin, foot (import_psd_to_spine "
        "names: arm_left, forearm_left, hand_left, leg_left, shin_left, foot_left)",
        "head parts apart: eyes (open, half, closed), pupils, brows, mouth shapes (rest, smile, "
        "open, o, wide), ears, each hair lock or tuft",
        "everything loose apart: tail, tie, scarf, cape panels, earrings, straps; long ones in "
        "one image that a mesh will bend",
        "props apart (cigar, glass, weapon, instrument), drawn whole even where a hand covers them",
    ],
    "hidden ends (underpaint)": [
        "every part is drawn COMPLETE, also where another part covers it: the top of the arm "
        "continues under the shoulder, the neck under the head and into the torso",
        "end each segment with a rounded cap centred on the joint, extending past the pivot by "
        "about half the limb's thickness: the parts can then rotate 40 degrees or more without "
        "opening a hole (check_art skeleton=... measures it: joint_gap)",
    ],
    "hands": [
        "a hand as one image only moves as a block: draw 4 to 6 hand poses per side (relaxed, "
        "open, fist, point, hold, snap) at the same wrist position and swap them with slot "
        "attachment keys on the pose change",
        "for a hero hand that must act: palm, thumb and each finger (or finger group) as "
        "separate parts, two bones per finger",
        "the wrist end goes under the cuff / sleeve; the cuff is its own part on the forearm",
    ],
    "clean cut-outs": [
        "transparent background, antialiased outline (no thresholded mask), no leftover pixels "
        "around the part, no halo of the old background, no see-through patch inside",
        "same resolution, line weight, palette and light direction for every part (generate "
        "them from the same reference sheet); work at 2x the size shown in the game",
        "leave the part its own canvas with a few transparent pixels around it; do not crop a "
        "limb where it should continue under its neighbour",
    ],
    "effects": [
        "smoke, sparks, impacts, glows: short frame-by-frame sequences (6 to 16 images named "
        "name_00, name_01...) on a region attachment with sequence_count, keyed with "
        'set_keyframes kind="sequence"; a puff of smoke also hides an attachment swap',
    ],
    "generating the parts with an image model": [
        "first a character sheet in the neutral pose (the reference for every later request)",
        "then one request per part, always with the sheet attached: 'the left forearm of this "
        "character alone, straight, vertical, complete with both rounded ends, same line "
        "weight and colours, transparent background, nothing else in the image'",
        "after each batch: check_art on the folder; clean_art for hard_edges / fragments; "
        "regenerate what has frayed_edges, light_fringe or soft_art, quoting the `fix` text",
        "after the rig: check_art(skeleton=...) and regenerate the parts named by joint_gap "
        "with the longer hidden end it asks for",
    ],
}

WORKFLOW = {
    "0 check the art": [
        'spine_reference("art") for how the parts must be drawn or generated',
        "check_art on the folder of parts: look at the annotated sheet, clean_art for "
        "hard_edges / fragments, redraw or regenerate the parts with the other warnings",
        "do not rig a part that still has a warning: a rig cannot fix a bad cut-out",
    ],
    "1 look at the rig": [
        "inspect_skeleton (summary) for bones, slots, constraints, animations",
        'runtime_render format="png" debug=true: where the pivots, bone directions, meshes and '
        "clipping polygons really are",
        "check_art(skeleton=...): joints that open a hole when bent, images drawn too large",
    ],
    "2 rig for animation": [
        "IK on legs and arms (add_ik_constraint create_target=true): feet can stay planted, hands "
        "can hold things; a limb needs TWO bones (thigh + shin) for a knee",
        "physics on everything that should lag: hair, ears, tails, cloth, belly (add_physics_constraint)",
        "meshes with weights where an image must bend (add_mesh_attachment + weight_bones)",
        "sliders for facial expressions / pose libraries, skins for outfits",
        "bones point along their limb with a length (add_bone length=..., world=true)",
    ],
    "3 block": [
        "key ONLY the storytelling poses first (contact, anticipation, extreme, settle) with "
        'set_keyframes; "curve": "stepped" while blocking',
        'runtime_render format="sheet" times=[key pose times]: are the silhouettes clear?',
        "or generate_animation for a base (idle, walk, run, jump, symbol_*) and adjust",
    ],
    "4 spline and polish": [
        "replace stepped with eased curves; slow in / slow out everywhere except constant-speed motion",
        "offset_keys(stagger=...) down each limb for overlapping action; physics for the rest",
        "scale_keys to exaggerate the main action (1.2 to 1.5), soften the secondary ones",
        "draw order keys when a limb passes in front / behind, events on contacts",
    ],
    "5 review (every time)": [
        "analyze_animation: fix warnings (loop pops, linear motion, dead keys, pops, foot slide)",
        'runtime_render format="sheet" on the game background, then format="onion" '
        "track_bones=[hand, foot, head]: arcs must be smooth curves, dot spacing must ease",
        "transitions: runtime_render animation=A overlays=[{track: 0, animation: B, start, mix}]",
        "runtime_sample when a number matters (foot height during contact, impact frame)",
    ],
    "6 deliver": [
        "runtime_validate (the game's runtime loads it)",
        "spine_import_data -> .spine project to open in Spine 4.3",
        "export_game_pack (binary + atlas, premultiplied alpha), editor_render for showcase "
        "videos, export_web_preview to review on a phone",
    ],
    "files": "skeletons are JSON paths; edits are validated and saved atomically",
}

QUALITY = {
    "how to judge": (
        "You cannot watch a GIF: review animation as STILLS. A contact sheet shows the poses, an "
        "onion render shows the motion (ghosts + one dot per frame on each tracked bone: close "
        "dots = slow, wide dots = fast, the dotted line is the arc), runtime_sample gives the "
        "numbers, analyze_animation lists what a lead would circle."
    ),
    "principles": {
        "squash and stretch": (
            "Keep the volume: scale y = 1/x. Bone scale is in BONE axes: on a bone pointing up "
            "(rotation 90) scale x is the vertical one. Stretch on fast moves, squash on "
            "impacts (1 to 3 frames), then settle. Tools: scale keys, a grid mesh for soft "
            'bodies, IK stretch=true with scale_y="volume", physics scale_x with scale_y="volume".'
        ),
        "anticipation": (
            "Before a main action, move the opposite way: 10 to 25 % of the action's amplitude, "
            "0.1 to 0.25 s, easeOut into the anticipation pose, then easeIn out of it. Bigger "
            "action = longer anticipation."
        ),
        "staging": (
            "One idea at a time and a readable silhouette at each key pose (check the sheet). "
            "Use set_draw_order_keys so the acting limb is in front; do not animate everything "
            "at the same amplitude."
        ),
        "pose to pose": (
            "Block the key poses with stepped curves, approve them on a sheet, only then add "
            "breakdowns and curves. Fewer, well-placed keys with bezier curves beat a key on "
            "every frame."
        ),
        "follow through and overlapping action": (
            "Parts do not start or stop together. Children lag their parent by 1 to 3 frames "
            "per joint (offset_keys bones=[shoulder, elbow, wrist] stagger=0.03 to 0.07); loose "
            "parts (hair, tails, cloth) use add_physics_constraint or the follow_through preset; "
            "after a stop, overshoot by 10 to 20 % and settle (easeOutBack, or an extra key)."
        ),
        "slow in and slow out": (
            'Linear interpolation reads as mechanical: give every moving segment a curve. '
            '"easeOut" after an impact or launch, "easeIn" into a hit or a fall, "easeInOut" / '
            '"easeInOutSine" for cycles and settles, "easeOutBack" for a pop with overshoot. '
            "Keep linear only for true constant speed: a planted foot sliding under the body, "
            "a wheel, a conveyor."
        ),
        "arcs": (
            "Limbs and heads travel on curves, not straight lines. Rotations give arcs for free; "
            "for translations key x and y on separate timelines with different easing "
            "(translatex linear + translatey easeOut then easeIn = a parabola). Check with "
            'runtime_render format="onion" track_bones=[...]: a kink in the dotted line is a '
            "broken arc."
        ),
        "secondary action": (
            "Layer small actions that support the main one: breathing, blink on track 1 "
            "(runtime_render overlays), ear / tail flick, a glance. Keep them smaller and off "
            "the main beats."
        ),
        "timing": (
            "Timing is weight and mood: the same poses at 4 frames or 12 frames are a snap or a "
            "drift. Fast in, slow out reads powerful; even timing reads robotic. Hold an impact "
            "pose 2 to 4 frames before settling. See `timing`."
        ),
        "exaggeration": (
            "Game characters are small on screen: push poses further than feels natural "
            "(scale_keys factor 1.2 to 1.5 on the main action), then verify the silhouette."
        ),
        "solid shapes": (
            "Keep volumes and joints believable: pivots at the joints (check debug render), no "
            "limb longer than its art, mesh bends under ~45 deg per segment unless weighted, "
            "draw order consistent with depth."
        ),
        "appeal": (
            "Avoid twinning (left and right doing the same thing on the same frames), break "
            "symmetry, keep the character alive during holds (moving hold: a few percent of "
            "drift or breathing instead of a frozen frame)."
        ),
    },
    "timing": {
        "frame": "1 frame at 30 fps = 0.0333 s (dopesheet fps is skeleton.fps)",
        "blink": "0.10 to 0.15 s closed-and-open, every 2 to 5 s, never on a regular beat",
        "anticipation": "0.10 to 0.25 s",
        "fast action (punch, slash, pop)": "0.07 to 0.15 s, then hold the extreme 0.07 to 0.13 s",
        "settle / overshoot": "0.2 to 0.4 s, damped",
        "idle loop": "2 to 4 s (breathing ~0.3 Hz); offset head / arms / tail by a fraction of the cycle",
        "walk cycle": "0.8 to 1.1 s for 2 steps; contact, down, passing, up poses per step",
        "run cycle": "0.5 to 0.7 s, both feet off the ground twice per cycle, body leans forward",
        "jump": "anticipation 0.2 s, takeoff 0.1 s, air 0.4 to 0.6 s, landing squash 0.1 s, recover 0.25 s",
        "hit reaction": "snap 0.05 to 0.1 s, hold 0.1 s, recover 0.3 s; tint-black flash 0.1 to 0.15 s",
        "UI / symbol pop": "0.25 to 0.4 s with overshoot; celebration loop 1 to 1.5 s",
    },
    "game rules": {
        "loops": (
            "Every timeline must end on its first value AND with the same slope, at the same "
            "duration. With physics, render with warmup=1 or 2. analyze_animation checks the seam."
        ),
        "transitions": (
            "Animations are mixed at runtime: start and end near a shared ready pose, and test "
            "A -> B with overlays track 0 and the game's mix duration. A property keyed in A "
            "and not in B returns to the setup pose during the mix."
        ),
        "tracks": (
            "Layer independent actions on tracks (blink, aim, hit flash) instead of baking them "
            "into every animation. A one-shot layer keys ONLY the parts that act, so the loop "
            "keeps playing under it. Games often set it without a mix-in: every bone it keys "
            "then jumps from wherever the loop left it to the layer's first key. Measure it: "
            "runtime_sample animation=<loop> overlays=[{track, animation, start, mix_out}] "
            "against the loop alone, on the entry frame, for several `start` values. A limb "
            "that leaves its IK target (hand lets go, waves, reaches the face) must not key the "
            "target: key its bones' rotations and fade the IK mix 1 -> 0 -> 1, so it starts "
            "from, and returns to, wherever the loop holds the target."
        ),
        "events": "Key events on contacts and impacts (add_event_keys): footsteps, hit frame, sound, VFX spawn. runtime_render / runtime_sample return the events fired.",
        "IK": (
            "An IK constraint at mix 1 overrides its bones' rotation keys. Animate the target, "
            "or key the IK mix to 0 for an FK section. A target out of reach locks the limb "
            "straight and the hand never follows its keys: runtime_sample the hand and its "
            "target, their distance must be 0. An IK key without bendPositive means true: a "
            "layer played alone and the same layer over a loop that keys the IK can bend the "
            "elbow opposite ways, so review layers over their loop, never alone."
        ),
        "performance": "Few keys with curves, modest mesh vertex counts, clipping only where needed (it is the most expensive attachment), binary export + premultiplied-alpha atlas (export_game_pack).",
        "glow": "Additive slots need a background to add light to: judge them with background=<game color>.",
    },
    "physics tuning": {
        "what the numbers do": (
            "inertia 0..1: how much of the bone's own movement is turned into swing. strength: "
            "the spring pulling back to the animated pose (higher = stiffer, faster wobble). "
            "damping: fraction of speed kept (close to 1 = swings for long, 0.8 = dies quickly). "
            "mass: heavier = slower to react. gravity / wind: constant pull, in reference-scale units."
        ),
        "hair / ears": "rotate=1, inertia 0.6 to 0.8, strength 120 to 200, damping 0.85 to 0.9, chain_falloff 0.15",
        "long tail / cape / cloth": "rotate=1, inertia 0.8 to 1, strength 60 to 100, damping 0.9 to 0.95, gravity 5 to 20",
        "belly / chest jiggle": 'x=0.3, y=1, scale_x=0.5, scale_y="volume", inertia 0.5, strength 200 to 300, damping 0.8',
        "tip": "Render with warmup=1+ and look at an onion of the chain tips; a physics chain needs the parent to MOVE to do anything.",
    },
}

RECIPES = {
    "attack (one-shot, ~0.8 s)": [
        "t=0 ready pose (= end pose, so it mixes back to idle)",
        "t=0.2 anticipation: body and weapon arm pulled back 15-25 % of the swing, curve easeOut",
        "t=0.3 strike extreme: curve easeIn into it (4 frames or less), body leans in, 10 % stretch",
        "t=0.4 hold the extreme (same pose, tiny drift), event 'hit' at t=0.3",
        "t=0.55 overshoot back past ready by 10 %, curve easeOut; t=0.8 ready, easeInOut",
        "offset_keys(bones=[arm, forearm, hand], offset=0, stagger=0.04, wrap=false) for drag; "
        "hair / cloth on physics",
    ],
    "walk on an IK rig": [
        "add_ik_constraint(bones=[thigh, shin], create_target=true) per leg (knee forward: "
        "bend_positive=false when facing +x)",
        'generate_animation preset="walk": planted feet, bent knees, arm swing, hip bob; the '
        "result gives ground_speed for the game",
        "analyze_animation(ground_bones=[foot targets]) -> contacts: key 'footstep' events there",
        "polish: offset_keys on spine / head (0.03 to 0.06), scale_keys on arm swing, physics on hair",
    ],
    "idle that feels alive": [
        'generate_animation preset="idle" (2 to 4 s), then offset_keys so chest, head and arms '
        "peak at different times",
        "blink as its own short animation, played on track 1 at irregular times by the game "
        '(preview: runtime_render overlays=[{"track": 1, "animation": "blink", "start": 1.3}])',
        "physics on hair / tail so they answer the breathing",
        "an occasional weight shift or glance every 2 or 3 cycles (a second, longer idle variant)",
    ],
    "impact / landing": [
        "last airborne frame stretched along the travel direction",
        "contact frame: squash 15-25 % (y = 1/x) within 1-2 frames, easeOut",
        "rebound past neutral by ~30 % of the squash, then settle in 0.2-0.3 s (easeInOutSine)",
        "shake preset on the root or camera bone for heavy hits, tint-black flash 0.1 s",
    ],
    "pop / appear (UI, symbol, pickup)": [
        "scale 0 -> 1.15 in 0.15 s easeOutBack, -> 0.97 in 0.08 s, -> 1 in 0.1 s",
        "rotate a few degrees against the scale overshoot, alpha 0 -> 1 in the first 0.1 s",
        "symbol_win / symbol_land / symbol_anticipation presets for reel symbols",
    ],
    "bending an image (tail, arm, cape)": [
        'add_mesh_attachment mode="grid" cols along the length (1 column per ~30 px), '
        "weight_bones=[chain]",
        "add_physics_constraint(bones=chain) or follow_through preset on the chain",
        'runtime_render debug={"meshes": true} to check the weights visually',
    ],
    "facial expression": [
        "one short animation per expression pose (brows, eyes, mouth bones or attachment swaps)",
        "add_slider per expression, driven by a control bone or keyed by time; mix them in any animation",
    ],
    "arm that must change pose (seated or holding character)": [
        "chain it: shoulder -> upper arm -> forearm -> hand, all children of the torso, never "
        "of the furniture",
        "to keep the hand on an armrest or a prop: add_ik_constraint(bones=[upper arm, "
        "forearm], create_target=true, target_parent=<the armrest or prop bone>); the body can "
        "then move while the hand stays put",
        "key the IK mix to 0 (set_keyframes kind=\"ik\") for the section where the arm acts, "
        "swap the hand drawing on the pose change (slot attachment key), and cover the swap "
        "with a fast move",
        "check_art(skeleton=...) for joint_gap at the shoulder, elbow and wrist before animating",
    ],
}

CHECKLIST = [
    "check_art has no warning on the parts and no joint_gap on the skeleton",
    "analyze_animation reports no warning (or each remaining one is deliberate); its "
    "`amplitude` shows the whole character alive, not a few moving bits",
    "sheet on the game background: every key pose has a clear silhouette, nothing clips or detaches",
    "onion with track_bones on hands / feet / head: smooth arcs, spacing eases in and out",
    "loops: no pop and no tick at the seam; physics rendered with warmup",
    "feet do not slide during contact; hips have weight (down after contact, up at passing)",
    "no frozen frame: holds keep a little life",
    "overlap: limbs and loose parts trail the body, they do not stop on the same frame",
    "transitions to and from the neighbouring animations tested with the game's mix duration",
    "one-shot layers reviewed OVER their loop (overlays + mix_out), started at several moments: "
    "entry jump of each keyed bone measured with runtime_sample; limbs that leave an IK target "
    "fade the IK mix instead of keying the target",
    "IK targets reachable: hand / foot to target distance is 0 in runtime_sample",
    "events on contacts / hits; draw order changes where limbs cross",
    "runtime_validate passes with the atlas the game will ship; durations and events unchanged "
    "when replacing an animation the game already triggers",
    "the report gives the measured numbers and lists what was NOT checked (real game, motion at "
    "speed, other screen sizes); 'no error' is never said from stills alone",
]
