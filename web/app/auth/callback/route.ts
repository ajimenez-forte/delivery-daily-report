import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";

// Google vuelve aquí con un código de un solo uso. Supabase lo cambia por la sesión.
export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get("code");
  const home = new URL("/", request.url);
  if (!code) return NextResponse.redirect(new URL("/login?error=1", request.url));
  const supabase = await createClient();
  const { error } = await supabase.auth.exchangeCodeForSession(code);
  return NextResponse.redirect(error ? new URL("/login?error=1", request.url) : home);
}
