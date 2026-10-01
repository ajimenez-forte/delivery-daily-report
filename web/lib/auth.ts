import "server-only";
import { cache } from "react";
import { forbidden, redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";

export type Identity = { userId: string; email: string; isUser: boolean; isAdmin: boolean; personId: number | null };

/**
 * Identidad del usuario. Sale solo del token de Supabase:
 *  1. getClaims() verifica la firma del token de la cookie de sesión.
 *  2. La base (mi_acceso) vuelve a revisar correo verificado, dominio y lista permitida.
 * Nunca se lee un correo de parámetros, encabezados ni cookies propias.
 */
export const getIdentity = cache(async (): Promise<Identity | null> => {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  const sub = data?.claims?.sub;
  if (error || !sub) return null;
  const { data: rows, error: dbError } = await supabase.rpc("mi_acceso");
  if (dbError || !rows?.[0]?.correo) return null;
  const r = rows[0];
  return { userId: sub, email: r.correo, isUser: !!r.es_usuario, isAdmin: !!r.es_admin, personId: r.person_id };
});

export async function requireUser(): Promise<Identity> {
  const id = await getIdentity();
  if (!id) redirect("/login");
  if (!id.isUser) forbidden();
  return id;
}

export async function requireAdmin(): Promise<Identity> {
  const id = await getIdentity();
  if (!id) redirect("/login");
  if (!id.isAdmin) forbidden();
  return id;
}
