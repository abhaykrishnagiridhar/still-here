(function () {
  var NS = 'http://www.w3.org/2000/svg';
  var host = document.getElementById('particles');
  if (!host) return;

  var COLORS = ['#8052ff', '#8052ff', '#ffb829', '#15846e', '#c24bd6', '#4a7bff'];
  var COUNT = 170;
  var LIGHT = { x: 380, y: 500 };
  var KEEP_OUT = [
    { x1: 164, y1: 342, x2: 596, y2: 524 },
    { x1: 0, y1: 430, x2: 172, y2: 640 }
  ];

  function rng(seed) {
    return function () {
      seed |= 0;
      seed = (seed + 0x6d2b79f5) | 0;
      var t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  var rand = rng(7);

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

  function clamp(n, lo, hi) {
    return Math.min(hi, Math.max(lo, n));
  }

  function point() {
    if (rand() < 0.65) {
      return {
        x: clamp(LIGHT.x + gaussian() * 150, -20, 700),
        y: clamp(LIGHT.y + gaussian() * 95, 285, 625)
      };
    }
    return { x: -20 + rand() * 720, y: 285 + rand() * 340 };
  }

  var frag = document.createDocumentFragment();
  var placed = 0;
  var guard = 0;

  while (placed < COUNT && guard < COUNT * 20) {
    guard += 1;
    var p = point();
    if (blocked(p.x, p.y)) continue;

    var s = 2.5 + rand() * 4.5;
    var tri = document.createElementNS(NS, 'polygon');
    tri.setAttribute(
      'points',
      '0,' + -s + ' ' + s * 0.87 + ',' + s * 0.5 + ' ' + -s * 0.87 + ',' + s * 0.5
    );
    tri.setAttribute('transform', 'translate(' + p.x.toFixed(1) + ' ' + p.y.toFixed(1) + ') rotate(' + Math.round(rand() * 360) + ')');
    tri.setAttribute('fill', 'none');
    tri.setAttribute('stroke', COLORS[Math.floor(rand() * COLORS.length)]);
    tri.setAttribute('stroke-width', '1');
    tri.setAttribute('opacity', (0.3 + rand() * 0.5).toFixed(2));

    if (rand() < 0.4) {
      tri.setAttribute('class', 'tw');
      tri.style.animationDelay = (rand() * 4).toFixed(2) + 's';
      tri.style.animationDuration = (2.5 + rand() * 3).toFixed(2) + 's';
    }

    frag.appendChild(tri);
    placed += 1;
  }

  host.appendChild(frag);
})();
