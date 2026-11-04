/* Restore gpstats.dev's VANTA.FOG artwork without blocking statistics or charts. */
'use strict';
(() => {
  const background = document.getElementById('gaia-background');
  const button = document.getElementById('art-motion');
  const header = document.querySelector('.gaia-masthead');
  if (!background || !button || !header) return;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let paused = false, visible = true, ready = false, effect = null, dependencies = null, failed = false, available = false, pageActive = true;
  try { paused = sessionStorage.getItem('gaia-background-motion') === 'paused'; } catch {}
  const eligible = () => ready && pageActive && !paused && !reduced.matches && !document.hidden && visible && !document.body.classList.contains('chart-focus');
  function script(src) {
    return new Promise((resolve, reject) => {
      const node = document.createElement('script');
      node.src = src; node.async = true; node.onload = resolve; node.onerror = reject;
      document.head.append(node);
    });
  }
  function controls() {
    button.hidden = reduced.matches || failed || (!available && !paused);
    button.textContent = paused ? 'Resume background motion' : 'Pause background motion';
    button.setAttribute('aria-pressed', String(paused));
  }
  function stop() {
    const current = effect;
    effect = null;
    if (!current) return;
    // Vanta 0.5.21 detaches the canvas but does not release Three's GPU resources.
    // It can also detach the canvas itself after swallowing an init failure.
    const renderer = current.renderer, scene = current.scene, canvas = renderer?.domElement;
    if (canvas?.parentNode !== current.el) current.renderer = null;
    try { current.destroy(); } catch {} // Cleanup must survive a partially initialized effect.
    const disposed = new Set();
    const dispose = resource => {
      if (!resource || disposed.has(resource)) return;
      disposed.add(resource);
      try { resource.dispose?.(); } catch {}
    };
    try { scene?.traverse(object => {
      dispose(object.geometry);
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.forEach(dispose);
    }); } catch {}
    dispose(renderer);
    try { renderer?.forceContextLoss?.(); } catch {}
    try { if (canvas?.parentNode) canvas.parentNode.removeChild(canvas); } catch {}
    current.renderer = null;
    current.scene = null;
  }
  async function sync() {
    if (!eligible() || failed) { stop(); controls(); return; }
    try {
      dependencies ||= script('/art/vendor/three.r119.min.js').then(() => script('/art/vendor/vanta.fog.min.js'));
      await dependencies;
      if (!eligible() || effect) return;
      // The same effect and color parameters used by Tim's original homepage.
      effect = window.VANTA.FOG({el: background, THREE: window.THREE,
        mouseControls: true, touchControls: true, gyroControls: false,
        minHeight: 200, minWidth: 200, highlightColor: 0x59ff00, midtoneColor: 0xef00ff});
      if (effect?.renderer?.domElement?.parentNode !== background || !effect.scene || !effect.camera) {
        throw new Error('Background initialization failed');
      }
      available = true;
    } catch {
      failed = true;
      // Constructors can throw after recording a partially initialized instance.
      if (!effect && window.VANTA?.current?.el === background) effect = window.VANTA.current;
      stop();
    }
    controls();
  }
  button.addEventListener('click', () => {
    paused = !paused;
    try { sessionStorage.setItem('gaia-background-motion', paused ? 'paused' : 'running'); } catch {}
    sync();
  });
  reduced.addEventListener('change', sync);
  document.addEventListener('visibilitychange', sync);
  new MutationObserver(sync).observe(document.body, {attributes: true, attributeFilter: ['class']});
  if ('IntersectionObserver' in window) new IntersectionObserver(entries => {
    visible = entries[0].isIntersecting; sync();
  }).observe(header);
  window.addEventListener('pagehide', () => { pageActive = false; stop(); controls(); });
  window.addEventListener('pageshow', () => { pageActive = true; sync(); });
  const start = () => { ready = true; sync(); };
  const idle = () => window.requestIdleCallback ? window.requestIdleCallback(start, {timeout: 1500}) : setTimeout(start, 0);
  if (document.readyState === 'complete') idle(); else window.addEventListener('load', idle, {once: true});
  controls();
})();
