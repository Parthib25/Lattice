/**
 * lattice-bg.js
 * 
 * DESIGN.md Compliant background.
 * A minimalist monospaced coordinate particle grid.
 * Sits flat behind the cream canvas.
 */
(function () {
  'use strict';

  const canvas = document.getElementById('lattice-canvas');
  if (!canvas || typeof THREE === 'undefined') return;

  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    powerPreference: 'low-power',
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
  renderer.setClearColor(0x000000, 0); // transparent background

  const scene = new THREE.Scene();
  let W = window.innerWidth;
  let H = window.innerHeight;

  const camera = new THREE.PerspectiveCamera(45, W / H, 0.1, 100);
  camera.position.z = 25;

  // Particle properties
  const particleCount = 70;
  const particles = new THREE.BufferGeometry();
  const positions = new Float32Array(particleCount * 3);
  const velocities = [];

  // Seed positions and velocities
  for (let i = 0; i < particleCount; i++) {
    // Spread coordinate points out across screen space
    positions[i * 3] = (Math.random() - 0.5) * 35;
    positions[i * 3 + 1] = (Math.random() - 0.5) * 20;
    positions[i * 3 + 2] = (Math.random() - 0.5) * 10;

    velocities.push({
      x: (Math.random() - 0.5) * 0.015,
      y: (Math.random() - 0.5) * 0.015,
      z: (Math.random() - 0.5) * 0.005
    });
  }

  particles.setAttribute('position', new THREE.BufferAttribute(positions, 3));

  // Render particles as tiny squares (monospaced look)
  const particleMaterial = new THREE.PointsMaterial({
    color: 0x646262, // Charcoal/mute gray
    size: 0.12,
    sizeAttenuation: true,
    transparent: true,
    opacity: 0.4
  });

  const pointCloud = new THREE.Points(particles, particleMaterial);
  scene.add(pointCloud);

  // Line connections segment pool
  const maxConnections = 120;
  const lineGeometry = new THREE.BufferGeometry();
  const linePositions = new Float32Array(maxConnections * 2 * 3);
  lineGeometry.setAttribute('position', new THREE.BufferAttribute(linePositions, 3));

  const lineMaterial = new THREE.LineBasicMaterial({
    color: 0x9a9898, // Ash gray connection lines
    transparent: true,
    opacity: 0.18
  });

  const lineMesh = new THREE.LineSegments(lineGeometry, lineMaterial);
  scene.add(lineMesh);

  function resize() {
    W = window.innerWidth;
    H = window.innerHeight;
    renderer.setSize(W, H);
    camera.aspect = W / H;
    camera.updateProjectionMatrix();
  }

  window.addEventListener('resize', resize, { passive: true });
  resize();

  // Animation Loop
  let raf;
  function animate() {
    raf = requestAnimationFrame(animate);

    const posArr = particles.attributes.position.array;
    const linePosArr = lineGeometry.attributes.position.array;

    // Move particles
    for (let i = 0; i < particleCount; i++) {
      posArr[i * 3] += velocities[i].x;
      posArr[i * 3 + 1] += velocities[i].y;
      posArr[i * 3 + 2] += velocities[i].z;

      // Bounce/wrap borders
      if (Math.abs(posArr[i * 3]) > 20) velocities[i].x *= -1;
      if (Math.abs(posArr[i * 3 + 1]) > 12) velocities[i].y *= -1;
      if (Math.abs(posArr[i * 3 + 2]) > 8) velocities[i].z *= -1;
    }
    particles.attributes.position.needsUpdate = true;

    // Connect close neighbors
    let lineIdx = 0;
    for (let i = 0; i < particleCount; i++) {
      const x1 = posArr[i * 3];
      const y1 = posArr[i * 3 + 1];
      const z1 = posArr[i * 3 + 2];

      for (let j = i + 1; j < particleCount; j++) {
        const x2 = posArr[j * 3];
        const y2 = posArr[j * 3 + 1];
        const z2 = posArr[j * 3 + 2];

        // Euclidean distance check
        const dist = Math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2 + (z1 - z2) ** 2);

        if (dist < 4.8 && lineIdx < maxConnections) {
          // Add line segment endpoints
          linePosArr[lineIdx * 6] = x1;
          linePosArr[lineIdx * 6 + 1] = y1;
          linePosArr[lineIdx * 6 + 2] = z1;

          linePosArr[lineIdx * 6 + 3] = x2;
          linePosArr[lineIdx * 6 + 4] = y2;
          linePosArr[lineIdx * 6 + 5] = z2;

          lineIdx++;
        }
      }
    }

    // Clear remaining slots in line coordinate buffer
    for (let i = lineIdx; i < maxConnections; i++) {
      linePosArr[i * 6] = 0;
      linePosArr[i * 6 + 1] = 0;
      linePosArr[i * 6 + 2] = 0;
      linePosArr[i * 6 + 3] = 0;
      linePosArr[i * 6 + 4] = 0;
      linePosArr[i * 6 + 5] = 0;
    }
    lineGeometry.attributes.position.needsUpdate = true;

    renderer.render(scene, camera);
  }

  // Lifecycle visibility control
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) cancelAnimationFrame(raf);
    else animate();
  });

  animate();
})();
