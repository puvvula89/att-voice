export function renderComponent(payload, onSelect) {
  const root = document.getElementById("ui-root");
  root.innerHTML = "";
  const map = { line_selector: optionList, phone_options: phoneList, confirmation, receipt };
  (map[payload.stage_intent] || (() => {}))(payload, root, onSelect);
}

function screenHeader(p, root) {
  if (p.title) {
    const h = document.createElement("h2");
    h.className = "screen-title";
    h.textContent = p.title;
    root.append(h);
  }
  if (p.message) {
    const m = document.createElement("p");
    m.className = "screen-msg";
    m.textContent = p.message;
    root.append(m);
  }
}

// line_selector — tappable rows
function optionList(p, root, onSelect) {
  screenHeader(p, root);
  const list = document.createElement("div");
  list.className = "option-list";
  (p.options || []).forEach((o) => {
    const row = document.createElement("button");
    row.className = "option-row";
    row.onclick = () => onSelect(o.submitValue);
    const main = document.createElement("div");
    const hd = document.createElement("div");
    hd.className = "opt-header";
    hd.textContent = o.header;
    const eb = document.createElement("div");
    eb.className = "opt-eyebrow";
    eb.textContent = o.eyebrow;
    main.append(hd, eb);
    const chev = document.createElement("span");
    chev.className = "chev";
    chev.textContent = "›";
    row.append(main, chev);
    list.append(row);
  });
  root.append(list);
}

// phone_options — product cards with image + price lockup
function phoneList(p, root, onSelect) {
  screenHeader(p, root);
  const grid = document.createElement("div");
  grid.className = "phone-grid";
  (p.options || []).forEach((o) => grid.append(phoneCard(o, onSelect)));
  root.append(grid);
}

function phoneCard(o, onSelect) {
  const c = document.createElement("div");
  c.className = "phone-card";
  c.onclick = () => onSelect(o.submitValue);

  const thumb = document.createElement("div");
  thumb.className = "phone-thumb";
  if (o.image && o.image.startsWith("data:")) {
    const img = document.createElement("img");
    img.src = o.image;
    img.alt = o.header;
    thumb.append(img);
  } else {
    thumb.textContent = "📱"; // placeholder until base64 images land (Batch C2)
  }
  c.append(thumb);

  if (o.eyebrow) {
    const eb = document.createElement("div");
    eb.className = "card-eyebrow";
    eb.textContent = o.eyebrow;
    c.append(eb);
  }
  const name = document.createElement("div");
  name.className = "card-name";
  name.textContent = o.header;
  c.append(name);

  if (o.price) c.append(priceLockup(o.price));

  if (o.tradeIn) {
    const chip = document.createElement("div");
    chip.className = "trade-chip";
    chip.textContent = `Up to $${o.tradeIn} trade-in`;
    c.append(chip);
  }
  return c;
}

function priceLockup(price) {
  const w = document.createElement("div");
  w.className = "price";
  if (price.prefix) {
    const pre = document.createElement("span");
    pre.className = "price-prefix";
    pre.textContent = price.prefix;
    w.append(pre);
  }
  const amt = document.createElement("span");
  amt.className = "price-amount";
  amt.textContent = "$" + price.amount;
  w.append(amt);
  if (price.suffix) {
    const suf = document.createElement("span");
    suf.className = "price-suffix";
    suf.textContent = price.suffix;
    w.append(suf);
  }
  return w;
}

// confirmation — summary + primary CTA
function confirmation(p, root, onSelect) {
  screenHeader(p, root);
  root.append(summaryTable(p.summary));
  if (p.primary) {
    const b = document.createElement("button");
    b.className = "primary-btn";
    b.textContent = p.primary.label;
    b.onclick = () => onSelect(p.primary.submitValue);
    root.append(b);
  }
}

// receipt — confirmation badge + summary
function receipt(p, root) {
  screenHeader(p, root);
  const badge = document.createElement("div");
  badge.className = "receipt-badge";
  badge.textContent = "✓";
  root.append(badge);
  root.append(summaryTable(p.summary));
}

function summaryTable(rows) {
  const t = document.createElement("div");
  t.className = "summary";
  (rows || []).forEach((r) => {
    const line = document.createElement("div");
    line.className = "summary-row";
    const l = document.createElement("span");
    l.className = "summary-label";
    l.textContent = r.label;
    const v = document.createElement("span");
    v.className = "summary-value";
    v.textContent = r.value;
    line.append(l, v);
    t.append(line);
  });
  return t;
}
