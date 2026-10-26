export type Theme = "light" | "dark";

export function resolveInitialTheme(stored: string | null, prefersLight: boolean): Theme {
  if (stored === "light" || stored === "dark") return stored;
  return prefersLight ? "light" : "dark";
}

// Leitura defensiva: localStorage pode lançar (storage bloqueado / iframe sandbox).
export function readStoredTheme(): string | null {
  try {
    return localStorage.getItem("theme");
  } catch {
    return null;
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem("theme", theme);
  } catch (e) {
    /* localStorage indisponível — ignora */
  }
}
