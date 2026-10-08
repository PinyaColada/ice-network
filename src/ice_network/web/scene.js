/* A small Three.js diorama. Heights come from the ledger; truck movement is illustrative. */
(() => {
  "use strict";
  const app = window.iceReplay,
    { data, state, projection } = app,
    T = window.ICE3D;
  const stage = document.getElementById("stage"),
    labelLayer = document.getElementById("scene-labels");
  let renderer;
  try {
    renderer = new T.WebGLRenderer({ antialias: true, alpha: false });
  } catch (error) {
    app.sceneError = String(error);
    document.getElementById("webgl-fallback").hidden = false;
    app.setView("2d");
    document.getElementById("view-3d").disabled = true;
    return;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = T.PCFSoftShadowMap;
  renderer.outputColorSpace = T.SRGBColorSpace;
  renderer.toneMapping = T.ACESFilmicToneMapping;
  renderer.domElement.setAttribute(
    "aria-label",
    "Rotatable 3D Mallorca with stock columns and delivery routes",
  );
  stage.prepend(renderer.domElement);
  const scene = new T.Scene();
  scene.background = new T.Color("#dce9e2");
  scene.fog = new T.Fog("#dce9e2", 190, 350);
  const camera = new T.PerspectiveCamera(34, 1, 0.1, 450);
  const controls = new T.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 75;
  controls.maxDistance = 220;
  controls.minPolarAngle = 0.15;
  controls.maxPolarAngle = Math.PI * 0.46;
  controls.enablePan = false;
  function reset() {
    const fit = Math.max(1, 1.65 / (stage.clientWidth / stage.clientHeight));
    camera.position.set(39, 81, 89).multiplyScalar(fit);
    controls.target.set(0, 0, 0);
    controls.update();
  }
  reset();
  document.getElementById("reset-camera").onclick = reset;
  scene.add(new T.HemisphereLight("#fffde8", "#7b9c90", 1.6));
  const sun = new T.DirectionalLight("#fff3d6", 2.1);
  sun.position.set(-55, 100, 45);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, {
    left: -70,
    right: 70,
    top: 70,
    bottom: -70,
    near: 1,
    far: 230,
  });
  sun.shadow.bias = -0.001;
  scene.add(sun);
  const material = (color, extra = {}) =>
    new T.MeshStandardMaterial({ color, roughness: 0.85, ...extra });
  const sand = material("#d7bb87"),
    grass = material("#96ab80"),
    white = material("#f5f5e9");
  const gold = material("#d4a65b"),
    ice = material("#4baca8", { roughness: 0.3, metalness: 0.12 });
  const sea = new T.Mesh(new T.PlaneGeometry(700, 700), material("#aaccc7"));
  sea.rotation.x = -Math.PI / 2;
  sea.position.y = -1.5;
  sea.receiveShadow = true;
  scene.add(sea);
  const shape = new T.Shape();
  app.coast.forEach(([lon, lat], i) => {
    const [x, z] = projection(lon, lat);
    if (i) shape.lineTo(x, -z);
    else shape.moveTo(x, -z);
  });
  shape.closePath();
  const landGeometry = new T.ExtrudeGeometry(shape, {
    depth: 1.2,
    bevelEnabled: true,
    bevelThickness: 0.45,
    bevelSize: 0.45,
    bevelSegments: 1,
    steps: 1,
  });
  landGeometry.rotateX(-Math.PI / 2);
  const beach = new T.Mesh(landGeometry, sand);
  beach.scale.set(1.035, 1, 1.035);
  beach.position.y = -1.2;
  beach.receiveShadow = true;
  scene.add(beach);
  const island = new T.Mesh(landGeometry, grass);
  island.position.y = -0.2;
  island.receiveShadow = true;
  island.castShadow = true;
  scene.add(island);
  // Low-poly hills orient the north-western spine; they are scenery, not elevation data.
  for (const [lon, lat, h] of [
    [2.48, 39.64, 3],
    [2.6, 39.69, 4.5],
    [2.72, 39.75, 5.3],
    [2.83, 39.81, 4],
    [2.95, 39.86, 3],
  ]) {
    const [x, z] = projection(lon, lat),
      hill = new T.Mesh(new T.ConeGeometry(4.5, h, 5), material("#a7b88a"));
    hill.position.set(x, 1 + h / 2, z);
    hill.rotation.y = lon;
    hill.receiveShadow = true;
    hill.castShadow = true;
    scene.add(hill);
  }
  const labels = [],
    pickables = [],
    bars = [];
  function label(text, position, bar = null, depot = false) {
    const el = document.createElement(bar === null ? "span" : "button");
    el.className = "scene-label" + (depot ? " depot" : "");
    el.textContent = text;
    labelLayer.append(el);
    if (bar !== null) {
      el.onclick = () => app.selectBar(bar);
      el.setAttribute("aria-label", data.bars[bar].name);
    }
    const entry = { el, position, bar, text };
    labels.push(entry);
    return entry;
  }
  const unitBox = new T.BoxGeometry(1, 1, 1);
  function box(w, h, d, mat, x, y, z, parent = scene) {
    const m = new T.Mesh(unitBox, mat);
    m.scale.set(w, h, d);
    m.position.set(x, y, z);
    m.castShadow = true;
    m.receiveShadow = true;
    parent.add(m);
    return m;
  }
  const height = (bags) => bags / 48;
  for (const b of data.bars) {
    const [x, z] = projection(b.lon, b.lat),
      maxHeight = height(b.capacity),
      g = new T.Group();
    g.position.set(x, 1.05, z);
    scene.add(g);
    const platform = box(4.1, 0.4, 3.5, white, 0, 0.1, 0, g);
    const fill = box(1.85, 1, 1.85, ice.clone(), 0, 0.5, 0, g);
    const frame = new T.LineSegments(
      new T.EdgesGeometry(new T.BoxGeometry(2, maxHeight, 2)),
      new T.LineBasicMaterial({ color: "#65958b", transparent: true, opacity: 0.55 }),
    );
    frame.position.y = maxHeight / 2 + 0.3;
    g.add(frame);
    const roof = new T.Mesh(
      new T.ConeGeometry(1.25, 0.65, 6),
      material(b.id % 2 ? "#dd9864" : "#e6c981"),
    );
    roof.position.set(2.2, 2.5, 0.3);
    g.add(roof);
    box(0.1, 2.3, 0.1, white, 2.2, 1.15, 0.3, g);
    const ring = new T.Mesh(new T.CylinderGeometry(2.7, 2.7, 0.09, 40), material("#d3b367"));
    ring.position.y = -0.06;
    g.add(ring);
    for (const m of [platform, fill, roof]) {
      m.userData.bar = b.id;
      pickables.push(m);
    }
    const caption = label(
      `${b.id + 1} ${b.name.split(":")[0]}`,
      new T.Vector3(x, maxHeight + 2, z),
      b.id,
    );
    bars.push({ g, fill, ring, caption, maxHeight });
  }
  for (const [d, depot] of data.depots.entries()) {
    const [x, z] = projection(depot.lon, depot.lat),
      g = new T.Group();
    g.position.set(x, 1, z);
    scene.add(g);
    box(6, 2.8, 4, white, 0, 1.4, 0, g);
    box(6.6, 0.4, 4.6, gold, 0, 3, 0, g);
    for (let k = 0; k < 3; k++)
      box(1, 0.9, 0.08, material("#80a5a0"), -1.8 + k * 1.8, 1.8, 2.05, g);
    label(`${depot.name} depot · ${depot.lead}d`, new T.Vector3(x, 5.8, z), null, true);
  }
  const routeGroup = new T.Group();
  scene.add(routeGroup);
  let vehicles = [];
  let motionKey = "",
    dayProgress = 0,
    lastFrame = null;
  const truckWhite = material("#faf7e8"),
    truckBlue = material("#2d817d"),
    returnBody = material("#cab4df"),
    returnCab = material("#8b5fb5"),
    rubber = material("#43534d");
  function rebuildRoutes() {
    for (const child of [...routeGroup.children]) {
      routeGroup.remove(child);
      child.traverse((o) => {
        if (o.geometry && o.geometry !== unitBox) o.geometry.dispose();
        if (o.userData.routeMaterial) o.material.dispose();
      });
    }
    vehicles = [];
    for (const order of app.activeOrders()) {
      const returning = app.truckJourney(order, app.day(), 0).returning;
      const depot = data.depots[order.depot],
        bar = data.bars[order.bar],
        a = projection(depot.lon, depot.lat),
        b = projection(bar.lon, bar.lat);
      const start = new T.Vector3(a[0], 2, a[1]),
        end = new T.Vector3(b[0], 2, b[1]);
      const middle = start.clone().add(end).multiplyScalar(0.5);
      middle.y = 4 + start.distanceTo(end) * 0.14;
      const curve = new T.QuadraticBezierCurve3(start, middle, end);
      const line = new T.Line(
        new T.BufferGeometry().setFromPoints(curve.getPoints(45)),
        new T.LineBasicMaterial({
          color: returning ? "#8b5fb5" : "#2d817d",
          transparent: true,
          opacity: order.bar === state.bar ? 0.9 : 0.42,
        }),
      );
      line.userData.routeMaterial = true;
      routeGroup.add(line);
      const truck = new T.Group();
      box(1.1, 0.8, 1.7, returning ? returnBody : truckWhite, 0, 0.4, -0.2, truck);
      box(1.1, 0.65, 0.65, returning ? returnCab : truckBlue, 0, 0.32, 0.9, truck);
      for (const x of [-0.57, 0.57])
        for (const z of [-0.65, 0.65]) {
          const wheel = new T.Mesh(new T.CylinderGeometry(0.22, 0.22, 0.14, 8), rubber);
          wheel.rotation.z = Math.PI / 2;
          wheel.position.set(x, 0, z);
          truck.add(wheel);
        }
      routeGroup.add(truck);
      vehicles.push({ truck, curve, order });
    }
  }
  function update() {
    const key = `${state.run}/${app.day()}`;
    if (key !== motionKey) {
      motionKey = key;
      dayProgress = 0;
      lastFrame = null;
    }
    for (const r of app.rows()) {
      const b = bars[r.bar],
        h = Math.max(0.04, height(r.closing));
      b.fill.scale.y = h;
      b.fill.position.y = 0.3 + h / 2;
      b.fill.material.color.set(r.sales < r.latent_demand ? "#c88259" : "#4baca8");
      b.ring.visible = r.bar === state.bar;
      b.caption.el.classList.toggle("selected", r.bar === state.bar);
      b.caption.el.classList.toggle("lost", r.sales < r.latent_demand);
      b.caption.el.title = `${data.bars[r.bar].name}: ${app.number(r.closing, 1)} bags at close`;
    }
    refreshLabels();
    rebuildRoutes();
  }
  function refreshLabels() {
    for (const entry of labels) {
      entry.el.textContent =
        stage.clientWidth < 500 && entry.bar !== null && entry.bar !== state.bar
          ? String(entry.bar + 1)
          : entry.text;
    }
  }
  function resize() {
    const { width, height } = stage.getBoundingClientRect();
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    refreshLabels();
  }
  new ResizeObserver(resize).observe(stage);
  resize();
  const raycaster = new T.Raycaster(),
    pointer = new T.Vector2();
  let down = [0, 0];
  renderer.domElement.addEventListener("pointerdown", (e) => {
    down = [e.clientX, e.clientY];
  });
  renderer.domElement.addEventListener("pointerup", (e) => {
    if (Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
    const r = renderer.domElement.getBoundingClientRect();
    pointer.set(
      ((e.clientX - r.left) / r.width) * 2 - 1,
      (-(e.clientY - r.top) / r.height) * 2 + 1,
    );
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(pickables, false)[0];
    if (hit) app.selectBar(hit.object.userData.bar);
  });
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  renderer.setAnimationLoop((time) => {
    if (state.view !== "3d" || document.hidden) {
      lastFrame = null;
      return;
    }
    const duration = state.timer ? Number(document.getElementById("speed").value) : 6000;
    if (lastFrame !== null) dayProgress = Math.min(1, dayProgress + (time - lastFrame) / duration);
    lastFrame = time;
    controls.update();
    for (const { truck, curve, order } of vehicles) {
      const { progress, returning } = app.truckJourney(
        order,
        app.day(),
        reduced ? 0.5 : dayProgress,
      );
      truck.position.copy(curve.getPoint(progress));
      const tangent = curve.getTangent(progress);
      truck.rotation.y = Math.atan2(tangent.x, tangent.z) + (returning ? Math.PI : 0);
      truck.userData.journey = { progress, returning };
    }
    renderer.render(scene, camera);
    const w = stage.clientWidth,
      h = stage.clientHeight;
    const occupied = [];
    for (const entry of [...labels].sort((a, b) => (b.bar === state.bar) - (a.bar === state.bar))) {
      const v = entry.position.clone().project(camera),
        x = ((v.x + 1) * w) / 2;
      let y = ((-v.y + 1) * h) / 2;
      const width = entry.el.offsetWidth || 70;
      for (let attempt = 0; attempt < 4; attempt++) {
        if (
          !occupied.some(
            (r) => Math.abs(r.x - x) < (r.width + width) / 2 + 3 && Math.abs(r.y - y) < 22,
          )
        )
          break;
        y -= 23;
      }
      occupied.push({ x, y, width });
      entry.el.style.left = x + "px";
      entry.el.style.top = y + "px";
      entry.el.hidden = v.z > 1 || Math.abs(v.x) > 0.95 || Math.abs(v.y) > 0.92;
    }
  });
  state.scene = {
    update,
    resize,
    renderer,
    camera,
    controls,
    inspectVehicles: () =>
      vehicles.map(({ truck, order }) => ({
        ...truck.userData.journey,
        arrival: order.arrival,
        depot: order.depot,
        bar: order.bar,
        color: truck.children[1].material.color.getHexString(),
        heading: truck.rotation.y,
        position: truck.position.toArray(),
      })),
  };
  update();
})();
