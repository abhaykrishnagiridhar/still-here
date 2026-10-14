(function () {
  var NS = 'http://www.w3.org/2000/svg';
  var COLORS = ['#8052ff', '#8052ff', '#ffb829', '#15846e', '#c24bd6', '#4a7bff'];
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function rng(seed) {
    return function () {
      seed |= 0;
      seed = (seed + 0x6d2b79f5) | 0;
      var t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function clamp(n, lo, hi) {
    return Math.min(hi, Math.max(lo, n));
  }

  function triangle(rand, x, y, size, opacity, twinkle) {
    var s = size;
    var tri = document.createElementNS(NS, 'polygon');
    tri.setAttribute(
      'points',
      '0,' + -s + ' ' + s * 0.87 + ',' + s * 0.5 + ' ' + -s * 0.87 + ',' + s * 0.5
    );
    tri.setAttribute('transform', 'translate(' + x.toFixed(1) + ' ' + y.toFixed(1) + ') rotate(' + Math.round(rand() * 360) + ')');
    tri.setAttribute('fill', 'none');
    tri.setAttribute('stroke', COLORS[Math.floor(rand() * COLORS.length)]);
    tri.setAttribute('stroke-width', '1');
    tri.setAttribute('opacity', opacity.toFixed(2));
    if (twinkle) {
      tri.setAttribute('class', 'tw');
      tri.style.animationDelay = (rand() * 4).toFixed(2) + 's';
      tri.style.animationDuration = (2.5 + rand() * 3).toFixed(2) + 's';
    }
    return tri;
  }

  /* Dense field inside the scene, brighter around the survivor light. */
  function sceneParticles() {
    var host = document.getElementById('particles');
    if (!host) return;

    var rand = rng(7);
    var COUNT = 520;
    var LIGHT = { x: 380, y: 500 };
    var X_MIN = -300;
    var X_MAX = 900;
    var Y_MIN = 252;
    var Y_MAX = 640;
    var KEEP_OUT = [
      { x1: 164, y1: 342, x2: 596, y2: 524 },
      { x1: 0, y1: 430, x2: 172, y2: 640 }
    ];

    function gaussian() {
      var u = 1 - rand();
      var v = rand();
      return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
    }

    function blocked(x, y) {
      return KEEP_OUT.some(function (r) {
        return x > r.x1 && x < r.x2 && y > r.y1 && y < r.y2;
      });
    }

    function point() {
      if (rand() < 0.4) {
        return {
          x: clamp(LIGHT.x + gaussian() * 210, X_MIN, X_MAX),
          y: clamp(LIGHT.y + gaussian() * 95, Y_MIN, Y_MAX)
        };
      }
      return {
        x: X_MIN + rand() * (X_MAX - X_MIN),
        y: Y_MIN + rand() * (Y_MAX - Y_MIN)
      };
    }

    var frag = document.createDocumentFragment();
    var placed = 0;
    var guard = 0;

    while (placed < COUNT && guard < COUNT * 20) {
      guard += 1;
      var p = point();
      if (blocked(p.x, p.y)) continue;
      frag.appendChild(triangle(rand, p.x, p.y, 2.5 + rand() * 4.5, 0.3 + rand() * 0.5, rand() < 0.4));
      placed += 1;
    }

    host.appendChild(frag);
  }

  /* Faint field behind the whole page so no area is empty. */
  function ambientParticles() {
    var svg = document.getElementById('ambient');
    if (!svg) return;

    var lastW = 0;
    var lastH = 0;

    function build() {
      var w = Math.round(svg.clientWidth);
      var h = Math.round(svg.clientHeight);
      if (!w || !h) return;
      if (Math.abs(w - lastW) < 40 && Math.abs(h - lastH) < 40) return;
      lastW = w;
      lastH = h;

      svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
      while (svg.firstChild) svg.removeChild(svg.firstChild);

      var rand = rng(21);
      var count = Math.min(900, Math.round((w * h) / 6500));
      var frag = document.createDocumentFragment();

      for (var i = 0; i < count; i += 1) {
        frag.appendChild(
          triangle(rand, rand() * w, rand() * h, 2.5 + rand() * 3.5, 0.12 + rand() * 0.28, rand() < 0.25)
        );
      }
      svg.appendChild(frag);
    }

    build();

    if (window.ResizeObserver) {
      new ResizeObserver(build).observe(svg);
    } else {
      window.addEventListener('resize', build);
    }
  }

  /* Scroll progress is 0 at the top of the page and 1 at the bottom. The CSS turns it into
     a fade from fully visible at the top to gone at the bottom. */
  function linkFadeToScroll() {
    var root = document.documentElement;
    var last = '';

    function update() {
      var scrollable = root.scrollHeight - window.innerHeight;
      var progress = scrollable > 1 ? clamp(window.scrollY / scrollable, 0, 1) : 0;
      var value = progress.toFixed(3);
      if (value !== last) {
        last = value;
        root.style.setProperty('--scroll', value);
      }
    }

    /* Two triggers, so a missed event or a skipped frame can never leave the fade stale. */
    function tick() {
      update();
      window.requestAnimationFrame(tick);
    }

    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    tick();
  }

  /* SMIL animation ignores the CSS reduced-motion query, so drop it here. */
  function stopArmIfReduced() {
    if (!reduceMotion) return;
    document.querySelectorAll('animateTransform').forEach(function (a) {
      a.parentNode.removeChild(a);
    });
  }

  /* Arriving on a page always starts at the top, so links like "Back to the start" never
     land partway down because the browser restored an old scroll position. A reload keeps
     its place, and a link with a #hash goes to that section. */
  function startAtTop() {
    if ('scrollRestoration' in history) history.scrollRestoration = 'manual';

    var entries = window.performance && performance.getEntriesByType
      ? performance.getEntriesByType('navigation')
      : [];
    var isReload = entries.length > 0 && entries[0].type === 'reload';

    if (!isReload && !window.location.hash) {
      window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
    }
  }

  startAtTop();
  sceneParticles();
  ambientParticles();
  linkFadeToScroll();
  stopArmIfReduced();
})();
