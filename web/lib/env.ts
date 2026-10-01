// Las dos variables públicas de Supabase. Son públicas por diseño: RLS protege los datos.
// No hay aquí ninguna llave secreta: la app nunca usa service_role.
export function supabaseEnv() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key) {
    throw new Error("Faltan NEXT_PUBLIC_SUPABASE_URL o NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY (ver docs/SUPABASE.md).");
  }
  return { url, key };
}
