import { useEffect, useState } from "react";

// Кастомные модальные окна вместо системных window.confirm/prompt.
// Промис-API: `if (await confirmDialog({...}))` / `const v = await promptDialog({...})`.

let _seq = 0;
const listeners = new Set();
let current = null; // { id, type, opts, resolve }

function emit() {
  for (const l of listeners) l(current);
}

export function confirmDialog(opts = {}) {
  return new Promise((resolve) => {
    current = { id: ++_seq, type: "confirm", opts, resolve };
    emit();
  });
}

export function promptDialog(opts = {}) {
  return new Promise((resolve) => {
    current = { id: ++_seq, type: "prompt", opts, resolve };
    emit();
  });
}

export function DialogHost() {
  const [state, setState] = useState(current);
  const [value, setValue] = useState("");

  useEffect(() => {
    const l = (s) => {
      setState(s);
      setValue(s?.opts?.defaultValue || "");
    };
    listeners.add(l);
    return () => listeners.delete(l);
  }, []);

  if (!state) return null;
  const { type, opts, resolve } = state;

  const close = (result) => {
    current = null;
    emit();
    resolve(result);
  };
  const onConfirm = () => close(type === "prompt" ? value : true);
  const onCancel = () => close(type === "prompt" ? null : false);

  return (
    <div className="dlg-overlay" onMouseDown={onCancel}>
      <div
        className="dlg-card"
        role="dialog"
        aria-modal="true"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape") onCancel();
          if (e.key === "Enter" && (type !== "prompt" || value)) onConfirm();
        }}
      >
        {opts.title && <h3 className="dlg-title">{opts.title}</h3>}
        {opts.message && <p className="dlg-msg">{opts.message}</p>}
        {type === "prompt" && (
          <input
            className="dlg-input"
            type={opts.password ? "password" : "text"}
            autoFocus
            value={value}
            placeholder={opts.placeholder || ""}
            onChange={(e) => setValue(e.target.value)}
          />
        )}
        <div className="dlg-actions">
          <button className="dlg-btn dlg-cancel" onClick={onCancel}>
            {opts.cancelText || "Отмена"}
          </button>
          <button
            className={"dlg-btn " + (opts.danger ? "dlg-danger" : "dlg-ok")}
            autoFocus={type !== "prompt"}
            onClick={onConfirm}
          >
            {opts.confirmText || "OK"}
          </button>
        </div>
      </div>
    </div>
  );
}
