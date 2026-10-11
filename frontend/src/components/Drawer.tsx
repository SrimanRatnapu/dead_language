"use client";
import { useEffect, useRef } from "react";
import { Icon } from "./Icon";

export function Drawer({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: React.ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    panel.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <>
      <div
        onClick={onClose}
        className={`fixed inset-0 z-30 bg-ink/20 transition-opacity duration-200 ${open ? "opacity-100" : "pointer-events-none opacity-0"}`}
      />
      <div
        ref={panel}
        tabIndex={-1}
        role="dialog" aria-modal={open}
        aria-label={title}
        aria-hidden={!open}
        data-open={open}
        className="drawer bg-surface text-ink fixed inset-y-0 right-0 z-40 flex w-[min(520px,100vw)] flex-col border-l border-line shadow-[var(--shadow)] outline-none"
      >
        <div className="flex h-12 shrink-0 items-center justify-between border-b border-line px-5">
          <h2 className="font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="press rounded p-1 text-muted hover:text-ink">
            <Icon name="close" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
      </div>
    </>
  );
}
