/* Headless renderer driven by spine2d_mcp.runtime.worker through Playwright.
 *
 * Uses the official spine-webgl runtime (window.spine), so what is rendered
 * here is what a web game renders: meshes, weights, deform, clipping, blend
 * modes, two-color tint, IK / transform / path / physics constraints and
 * sliders are all evaluated by Esoteric's own code.
 *
 * Coordinates: Spine world units, y-up. The camera is an orthographic camera
 * centered on the requested bounds.
 */
(function () {
  "use strict";
  const S = window.spine;
  let canvas, ctx, gl, renderer, assets, data, atlas, cfg;

  // Runtime compatibility: 4.3 (setupPose, unified constraints), 4.2
  // (setToSetupPose, physics), 4.1 and older (no physics).
  function setupPose(sk) {
    if (sk.setupPose) sk.setupPose();
    else sk.setToSetupPose();
  }

  function constraintCounts(d) {
    if (!d.constraints) {
      return {
        ik: (d.ikConstraints || []).length, transform: (d.transformConstraints || []).length,
        path: (d.pathConstraints || []).length, physics: (d.physicsConstraints || []).length,
        slider: 0, other: 0,
      };
    }
    return null;
  }

  function describe(d) {
    const kinds = constraintCounts(d) || { ik: 0, transform: 0, path: 0, physics: 0, slider: 0, other: 0 };
    for (const c of d.constraints || []) {
      if (c instanceof S.IkConstraintData) kinds.ik++;
      else if (c instanceof S.TransformConstraintData) kinds.transform++;
      else if (c instanceof S.PathConstraintData) kinds.path++;
      else if (c instanceof S.PhysicsConstraintData) kinds.physics++;
      else if (S.SliderData && c instanceof S.SliderData) kinds.slider++;
      else kinds.other++;
    }
    const attachments = {};
    let attachmentCount = 0;
    for (const skin of d.skins) {
      for (const e of skin.getAttachments()) {
        attachmentCount++;
        const t = e.attachment.constructor && e.attachment.constructor.name || "attachment";
        attachments[t] = (attachments[t] || 0) + 1;
      }
    }
    return {
      name: d.name,
      version: d.version,
      hash: d.hash,
      x: d.x, y: d.y, width: d.width, height: d.height,
      fps: d.fps,
      referenceScale: d.referenceScale,
      imagesPath: d.imagesPath,
      bones: d.bones.length,
      slots: d.slots.length,
      skins: d.skins.map((s) => s.name),
      events: d.events.map((e) => e.name),
      animations: d.animations.map((a) => ({ name: a.name, duration: a.duration, timelines: a.timelines.length })),
      constraints: kinds,
      attachments: attachmentCount,
      attachmentTypes: attachments,
      atlasPages: atlas.pages.map((p) => ({ name: p.name, width: p.width, height: p.height, pma: !!p.pma })),
      runtime: S.SkeletonJson ? "spine-webgl" : "?",
      atlasRegions: atlas.regions.length,
    };
  }

  function instance() {
    const sk = new S.Skeleton(data);
    if (cfg.skin) {
      if (!data.findSkin(cfg.skin)) throw new Error("skin not found: " + cfg.skin);
      sk.setSkin(cfg.skin);
    }
    setupPose(sk);
    const stateData = new S.AnimationStateData(data);
    // Crossfade between consecutive animations of a track, as set in the game.
    stateData.defaultMix = cfg.mix || 0;
    const st = new S.AnimationState(stateData);
    // t0: playhead when the capture starts (after warm-up); event times are relative to it.
    const inst = { sk, st, t: 0, t0: 0, overlays: [], events: [] };
    // Events are dated at their key, not at the end of the step that fired them:
    // playhead - (animation time now - key time), one loop back if the step wrapped.
    // `at` (absolute playhead) lets startCapture() drop the warm-up ones only.
    st.addListener({
      event: (entry, ev) => {
        let at = inst.t;
        if (entry.getAnimationTime && entry.animation && ev.time != null) {
          const dur = entry.animation.duration;
          let back = entry.getAnimationTime() - ev.time;
          if (back < -1e-6 && dur > 0) back += dur;
          const speed = (entry.timeScale || 1) * (st.timeScale || 1);
          if (back >= 0 && back <= dur + 1e-6) at = inst.t - back / speed;
        }
        inst.events.push({
          at, name: ev.data.name, track: entry.trackIndex,
          animation: entry.animation ? entry.animation.name : null,
        });
      },
    });
    if (cfg.animation) {
      if (!data.findAnimation(cfg.animation)) throw new Error("animation not found: " + cfg.animation);
      st.setAnimation(0, cfg.animation, cfg.loop !== false);
    }
    // Animations set later: [{track, animation, start, loop, mix}], fired when the playhead
    // reaches `start`, exactly as a game state machine would set them. Track 1+ layers on
    // top (blink); track 0 replaces the main animation (transition test, with `mix`).
    inst.overlays = (cfg.overlays || []).map((o) => Object.assign({ fired: false }, o))
      .sort((a, b) => a.start - b.start);
    for (const o of inst.overlays) {
      if (!data.findAnimation(o.animation)) throw new Error("animation not found: " + o.animation);
    }
    fire(inst);
    step(inst, 0);
    return inst;
  }

  // Start of the capture: drop the events keyed before it (warm-up) but keep the
  // ones keyed exactly at its start, which fire in the initial zero step or in the
  // last warm-up step that reaches the loop boundary.
  function startCapture(inst) {
    inst.t0 = inst.t;
    inst.events = inst.events.filter((e) => e.at >= inst.t0 - 1e-5);
  }

  // Events as returned to Python: {time, name, track, animation}, time relative to t0.
  function eventsOf(inst) {
    return inst.events.map((e) => ({
      time: Math.round(Math.max(0, e.at - inst.t0) * 1e4) / 1e4 + 0,
      name: e.name, track: e.track, animation: e.animation,
    }));
  }

  function fire(inst) {
    for (const o of inst.overlays) {
      if (!o.fired && inst.t >= o.start - 1e-6) {
        const entry = inst.st.setAnimation(o.track == null ? 1 : o.track, o.animation, !!o.loop);
        if (o.mix != null) entry.mixDuration = o.mix;
        o.fired = true;
      }
    }
  }

  // World transform of every requested bone AFTER constraints and physics:
  // [x, y, rotation, scaleX, scaleY] per bone, flattened in `names` order.
  function boneNames(sk, wanted) {
    const all = sk.bones.map((b) => b.data.name);
    if (!wanted || !wanted.length || wanted.indexOf("*") >= 0) return all;
    for (const n of wanted) if (all.indexOf(n) < 0) throw new Error("bone not found: " + n);
    return wanted;
  }

  function snapshot(sk, names) {
    const out = [];
    const r = (v) => Math.round(v * 1e3) / 1e3;
    for (const n of names) {
      const b = sk.findBone(n);
      const p = b.appliedPose || b; // 4.3: BonePose, 4.2 and older: the bone itself
      out.push(r(p.worldX), r(p.worldY), r(Math.atan2(p.c, p.a) * 180 / Math.PI),
        r(Math.hypot(p.a, p.c)), r(Math.hypot(p.b, p.d)));
    }
    return out;
  }

  function drawDebug(sk, opts) {
    const d = renderer.skeletonDebugRenderer;
    const on = (k, def) => (opts[k] == null ? def : !!opts[k]);
    d.drawBones = on("bones", true);
    d.drawRegionAttachments = on("regions", false);
    d.drawMeshHull = on("meshes", true);
    d.drawMeshTriangles = on("triangles", true);
    d.drawBoundingBoxes = on("bounding_boxes", true);
    d.drawPaths = on("paths", true);
    d.drawClipping = on("clipping", true);
    if (S.Skeleton.prototype.setupPose) renderer.drawSkeletonDebug(sk);
    else renderer.drawSkeletonDebug(sk, true);
  }

  function step(inst, dt) {
    inst.t += dt;
    fire(inst);
    inst.st.update(dt);
    inst.st.apply(inst.sk);
    if (S.Physics) {
      if (inst.sk.update) inst.sk.update(dt);
      inst.sk.updateWorldTransform(S.Physics.update);
    } else {
      inst.sk.updateWorldTransform();
    }
  }

  // Advance `seconds` in steps of at most 1/fps so physics integrates the
  // same way it does at runtime.
  function advance(inst, seconds, fps) {
    const h = 1 / fps;
    let left = seconds;
    while (left > 1e-9) {
      const dt = Math.min(h, left);
      step(inst, dt);
      left -= dt;
    }
  }

  function boundsOf(sk) {
    const clipper = new S.SkeletonClipping();
    let r;
    if (sk.getBoundsRect) r = sk.getBoundsRect(clipper);
    else {
      const off = new S.Vector2(), size = new S.Vector2();
      sk.getBounds(off, size, [], clipper);
      r = { x: off.x, y: off.y, width: size.x, height: size.y };
    }
    if (!isFinite(r.x) || !isFinite(r.width) || r.width <= 0 || r.height <= 0) return null;
    return r;
  }

  window.spineMcp = {
    async load(c) {
      cfg = c;
      try {
        canvas = document.getElementById("c");
        canvas.width = 16;
        canvas.height = 16;
        ctx = new S.ManagedWebGLRenderingContext(canvas, {
          alpha: true, premultipliedAlpha: true, preserveDrawingBuffer: true, antialias: true,
        });
        gl = ctx.gl;
        renderer = new S.SceneRenderer(canvas, ctx, true);
        assets = new S.AssetManager(ctx, "");
        assets.loadTextureAtlas(c.atlas);
        if (c.binary) assets.loadBinary(c.skeleton);
        else assets.loadJson(c.skeleton);
        try {
          await assets.loadAll();
        } catch (errs) {
          return { ok: false, stage: "load", error: JSON.stringify(errs) };
        }
        atlas = assets.require(c.atlas);
        const loader = new S.AtlasAttachmentLoader(atlas);
        const reader = c.binary ? new S.SkeletonBinary(loader) : new S.SkeletonJson(loader);
        reader.scale = c.dataScale || 1;
        try {
          data = reader.readSkeletonData(assets.require(c.skeleton));
        } catch (e) {
          return { ok: false, stage: "parse", error: String((e && e.message) || e) };
        }
        const info = describe(data);
        // Setup pose sanity check: build an instance and pose it once.
        try {
          const inst = instance();
          info.setupBounds = boundsOf(inst.sk);
        } catch (e) {
          return { ok: false, stage: "pose", error: String((e && e.message) || e), info };
        }
        return { ok: true, info, webgl: gl instanceof WebGL2RenderingContext ? 2 : 1 };
      } catch (e) {
        return { ok: false, stage: "init", error: String((e && e.stack) || e) };
      }
    },

    // Union of the skeleton bounds over the sampled times (after warm-up).
    measure(times, fps, warmup) {
      const inst = instance();
      const dur = cfg.animation ? data.findAnimation(cfg.animation).duration : 0;
      if (warmup > 0 && dur > 0) advance(inst, warmup * dur, fps);
      let t = 0, box = null;
      for (const target of times) {
        advance(inst, target - t, fps);
        t = target;
        const r = boundsOf(inst.sk);
        if (!r) continue;
        if (!box) box = { x0: r.x, y0: r.y, x1: r.x + r.width, y1: r.y + r.height };
        else {
          box.x0 = Math.min(box.x0, r.x); box.y0 = Math.min(box.y0, r.y);
          box.x1 = Math.max(box.x1, r.x + r.width); box.y1 = Math.max(box.y1, r.y + r.height);
        }
      }
      if (!box) return null;
      return { x: box.x0, y: box.y0, width: box.x1 - box.x0, height: box.y1 - box.y0 };
    },

    // Streaming render: begin() sets up the camera and a fresh instance,
    // next(n) renders the next n frames and returns their PNG data URLs (so
    // big animations never travel as one huge message).
    // view: {cx, cy, worldW, worldH, pxW, pxH, outW, outH, background}
    // opts: {track: [bone names] | null, debug: {bones, meshes, ...} | null}
    begin(times, fps, warmup, view, opts) {
      canvas.width = view.pxW;
      canvas.height = view.pxH;
      gl.viewport(0, 0, view.pxW, view.pxH);
      const cam = renderer.camera;
      cam.position.x = view.cx;
      cam.position.y = view.cy;
      cam.zoom = 1;
      cam.setViewport(view.worldW, view.worldH);
      cam.update();
      const inst = instance();
      const dur = cfg.animation ? data.findAnimation(cfg.animation).duration : 0;
      if (warmup > 0 && dur > 0) advance(inst, warmup * dur, fps);
      startCapture(inst);
      let small = null, sctx = null;
      // Supersampling: draw at pxW x pxH, downscale in a 2D canvas (the
      // browser resamples premultiplied, so edges stay clean) and encode
      // only the final-size image.
      if (view.outW && (view.outW !== view.pxW || view.outH !== view.pxH)) {
        small = document.createElement("canvas");
        small.width = view.outW;
        small.height = view.outH;
        sctx = small.getContext("2d");
        sctx.imageSmoothingEnabled = true;
        sctx.imageSmoothingQuality = "high";
      }
      const o = opts || {};
      this._job = {
        inst, times, fps, i: 0, t: 0, view, small, sctx, bg: view.background || [0, 0, 0, 0],
        debug: o.debug || null, names: o.track ? boneNames(inst.sk, o.track) : null, samples: [],
      };
      return times.length;
    },

    next(n) {
      const j = this._job;
      const out = [];
      while (j.i < j.times.length && out.length < n) {
        const target = j.times[j.i++];
        advance(j.inst, target - j.t, j.fps);
        j.t = target;
        const bg = j.bg;
        gl.clearColor(bg[0] * bg[3], bg[1] * bg[3], bg[2] * bg[3], bg[3]);
        gl.clear(gl.COLOR_BUFFER_BIT);
        renderer.begin();
        renderer.drawSkeleton(j.inst.sk, -1, -1);
        if (j.debug) drawDebug(j.inst.sk, j.debug);
        renderer.end();
        if (j.names) j.samples.push(snapshot(j.inst.sk, j.names));
        if (j.small) {
          j.sctx.clearRect(0, 0, j.view.outW, j.view.outH);
          j.sctx.drawImage(canvas, 0, 0, j.view.outW, j.view.outH);
          out.push(j.small.toDataURL("image/png"));
        } else {
          out.push(canvas.toDataURL("image/png"));
        }
      }
      return out;
    },

    // Bone samples and fired events of the render started by begin().
    finish() {
      const j = this._job;
      return { bones: j.names, frames: j.samples, events: eventsOf(j.inst) };
    },

    // Same as a render without drawing: bone world transforms per time.
    sample(times, fps, warmup, wanted) {
      const inst = instance();
      const dur = cfg.animation ? data.findAnimation(cfg.animation).duration : 0;
      if (warmup > 0 && dur > 0) advance(inst, warmup * dur, fps);
      startCapture(inst);
      const names = boneNames(inst.sk, wanted);
      const frames = [];
      let t = 0;
      for (const target of times) {
        advance(inst, target - t, fps);
        t = target;
        frames.push(snapshot(inst.sk, names));
      }
      return { bones: names, frames, events: eventsOf(inst) };
    },
  };
  window.spineMcpReady = true;
})();
