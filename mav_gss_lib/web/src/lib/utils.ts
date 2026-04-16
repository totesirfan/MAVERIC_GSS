import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function isInputFocused(): boolean {
  const tag = document.activeElement?.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' ||
    (document.activeElement as HTMLElement)?.isContentEditable === true
}
