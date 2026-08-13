import React, { useEffect, useRef, useState } from "react";
import * as J from "../jalali.js";
import "./rep-report.css";

/* A Jalali date input: type `1404/05/22` (Persian digits welcome) or pick from
   the calendar popover. All arithmetic goes through src/jalali.js, which is the
   exact counterpart of the backend converter — nothing here re-implements dates.

   `value` / `onChange` speak the helper's [jy, jm, jd] parts (or null = empty). */

// شنبه → ش, یک‌شنبه → ی … the first letter is the usual Persian abbreviation.
const WD = J.WEEKDAYS.map((w) => w.charAt(0));

function Calendar({ value, onPick, onClose }) {
  const base = value || J.today();
  const [view, setView] = useState([base[0], base[1]]);
  const [vy, vm] = view;
  const step = (delta) => {
    const [ny, nm] = J.addMonths([vy, vm, 1], delta);
    setView([ny, nm]);
  };

  const lead = J.firstWeekdayOfMonth(vy, vm);   // 0 = Saturday = first column
  const total = J.monthDays(vy, vm);
  const [ty, tm, td] = J.today();
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push(null);
  for (let d = 1; d <= total; d++) cells.push(d);

  return (
    <div className="jcal" onMouseDown={(e) => e.stopPropagation()}>
      <div className="jcal-head">
        {/* RTL: the first child sits on the RIGHT, so "previous" comes first —
            same direction the Pager buttons use. */}
        <div className="jcal-navs">
          <button type="button" className="jcal-nav" title="سال قبل" onClick={() => step(-12)}>»</button>
          <button type="button" className="jcal-nav" title="ماه قبل" onClick={() => step(-1)}>›</button>
        </div>
        <div className="jcal-title">{J.MONTHS[vm - 1]} {vy}</div>
        <div className="jcal-navs">
          <button type="button" className="jcal-nav" title="ماه بعد" onClick={() => step(1)}>‹</button>
          <button type="button" className="jcal-nav" title="سال بعد" onClick={() => step(12)}>«</button>
        </div>
      </div>

      <div className="jcal-grid jcal-wd">{WD.map((w, i) => <span key={i}>{w}</span>)}</div>

      <div className="jcal-grid">
        {cells.map((d, i) => (d === null ? <span key={`b${i}`} /> : (
          <button
            key={d}
            type="button"
            className={"jcal-d"
              + (value && value[0] === vy && value[1] === vm && value[2] === d ? " on" : "")
              + (ty === vy && tm === vm && td === d ? " today" : "")}
            onClick={() => onPick([vy, vm, d])}
          >{d}</button>
        )))}
      </div>

      <div className="jcal-foot">
        <button type="button" className="btn xs" onClick={() => onPick(J.today())}>امروز</button>
        <button type="button" className="btn xs ghost" onClick={onClose}>بستن</button>
      </div>
    </div>
  );
}

export default function JalaliDateField({ label, value, onChange, placeholder = "1404/05/22" }) {
  const wire = value ? J.format(value) : "";
  const [text, setText] = useState(wire);
  const [open, setOpen] = useState(false);
  const box = useRef(null);

  // Follow the value when the parent changes it (e.g. seeding a custom range).
  useEffect(() => { setText(wire); }, [wire]);

  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const bad = text.trim() !== "" && !J.parse(text);
  const typed = (v) => {
    setText(v);
    const parts = J.parse(v);
    if (parts) onChange(parts);
    else if (!v.trim()) onChange(null);
  };
  const pick = (parts) => { setText(J.format(parts)); onChange(parts); setOpen(false); };

  return (
    <div className="jfield" ref={box}>
      {label ? <label className="jfield-lbl">{label}</label> : null}
      <div className="jfield-box">
        <input
          className={"inp jfield-inp" + (bad ? " bad" : "")}
          dir="ltr"
          inputMode="numeric"
          value={text}
          placeholder={placeholder}
          onChange={(e) => typed(e.target.value)}
          onFocus={() => setOpen(true)}
        />
        <button type="button" className="jfield-btn" title="تقویم" onClick={() => setOpen((s) => !s)}>📅</button>
      </div>
      {bad
        ? <span className="jfield-err">فرمت درست: 1404/05/22</span>
        : (value ? <span className="jfield-hint">{J.formatLong(value)}</span> : null)}
      {open && <Calendar value={value} onPick={pick} onClose={() => setOpen(false)} />}
    </div>
  );
}
