// Reserve the former demo URL so the dynamic section route cannot stream a
// misleading HTTP 200 for it. No demo components enter the production bundle.
export function GET() {
  return new Response("Такой страницы нет", {
    status: 404,
    headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
  });
}
