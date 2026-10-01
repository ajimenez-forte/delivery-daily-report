import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

// Corre antes de cada página. Hace tres cosas:
//  1. Refresca la sesión de Supabase (cookies).
//  2. Sin sesión válida, manda al login.
//  3. En /admin, si la base dice que no es admin, responde 403.
// La identidad sale solo del token verificado (getClaims) y de la base.
const PUBLIC = ["/login", "/auth/callback"];

export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request });
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll(list) {
          for (const { name, value } of list) request.cookies.set(name, value);
          response = NextResponse.next({ request });
          for (const { name, value, options } of list) response.cookies.set(name, value, options);
        },
      },
    },
  );

  const { data } = await supabase.auth.getClaims();
  const path = request.nextUrl.pathname;
  if (PUBLIC.some((p) => path === p || path.startsWith(p + "/"))) return response;

  if (!data?.claims?.sub) {
    if (path.startsWith("/api/")) return new NextResponse("Sin sesión", { status: 401 });
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    return NextResponse.redirect(url);
  }

  if (path.startsWith("/admin")) {
    const { data: rows } = await supabase.rpc("mi_acceso");
    if (!rows?.[0]?.es_admin) {
      return new NextResponse("Esta sección es solo para el rol admin.", {
        status: 403,
        headers: { "content-type": "text/plain; charset=utf-8" },
      });
    }
  }
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
