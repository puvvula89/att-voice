export function renderComponent(payload, onSelect) {
  const root = document.getElementById("ui-root");
  root.innerHTML = "";
  const map = { line_selector, phone_options, confirmation, receipt };
  (map[payload.stage_intent] || (() => {}))(payload, root, onSelect);
}

function line_selector(p, root, onSelect) {
  root.append(heading(p.title));
  p.data.lines.forEach(l => root.append(
    button(`Line ending ${l.last4} — ${l.device}`, () => onSelect(l.line_id))
  ));
}
function phone_options(p, root, onSelect) {
  root.append(heading(p.title));
  p.data.phones.forEach(ph => root.append(
    card(ph.name, ph.image, `$${ph.monthly_price}/mo`, () => onSelect(ph.phone_id))
  ));
}
function confirmation(p, root, onSelect) {
  root.append(heading(p.title));
  root.append(text(`${p.data.phone} on line ${p.data.line} — $${p.data.monthly_price}/mo`));
  root.append(button(p.confirm_label, () => onSelect("yes, confirm")));
}
function receipt(p, root) {
  root.append(heading(p.title));
  root.append(text(`Order ${p.data.order_id} — ships in ${p.data.ship_estimate}`));
}

function heading(t){const h=document.createElement("h2");h.textContent=t;return h;}
function text(t){const d=document.createElement("p");d.textContent=t;return d;}
function button(label,fn){const b=document.createElement("button");b.textContent=label;b.onclick=fn;return b;}
function card(name,img,price,fn){const c=document.createElement("div");c.className="card";c.onclick=fn;
  c.innerHTML=`<img src="${img}" alt="${name}"/><div>${name}</div><div>${price}</div>`;return c;}
