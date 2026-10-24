const publicPaths = new Set(["/login", "/register", "/forgot-password", "/reset-password", "/privacy"]);

export function isPublicPath(pathname: string) {
  return publicPaths.has(pathname);
}

export function safeRedirect(value: string | null | undefined, fallback = "/overview") {
  if (!value || !value.startsWith("/") || value.startsWith("//") || /[\\\u0000-\u001f]/.test(value)) return fallback;
  const pathname = value.split(/[?#]/, 1)[0].replace(/\/+$/, "") || "/";
  return isPublicPath(pathname) ? fallback : value;
}
