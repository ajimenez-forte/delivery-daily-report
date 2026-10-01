import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { supabaseEnv } from "@/lib/env";

// Cliente de Supabase para el servidor, con la sesión del usuario (cookies de Supabase).
// Todas las consultas pasan por RLS con el token del usuario.
export async function createClient() {
  const { url, key } = supabaseEnv();
  const cookieStore = await cookies();
  return createServerClient(url, key, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(list) {
        try {
          for (const { name, value, options } of list) cookieStore.set(name, value, options);
        } catch {
          // En un Server Component no se pueden escribir cookies. El proxy refresca la sesión.
        }
      },
    },
  });
}
