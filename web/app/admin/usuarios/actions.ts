"use server";
import { revalidatePath } from "next/cache";
import { requireAdmin } from "@/lib/auth";
import { createClient } from "@/lib/supabase/server";

const EMAIL = /^[^@\s]+@forteglobal\.com$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const TZ = new Set(["America/Bogota", "America/Costa_Rica"]);
const COUNTRY_TZ: Record<string, string> = { CO: "America/Bogota", CR: "America/Costa_Rica" };

function str(f: FormData, k: string) {
  return String(f.get(k) ?? "").trim();
}

async function db() {
  await requireAdmin();
  return createClient();
}

function done(error: { message: string } | null) {
  if (error) throw new Error(error.message);
  revalidatePath("/admin/usuarios");
}

export async function guardarUsuario(f: FormData) {
  const supabase = await db();
  const email = str(f, "email").toLowerCase();
  if (!EMAIL.test(email)) throw new Error("Solo se aceptan correos @forteglobal.com.");
  const role = str(f, "role") === "admin" ? "admin" : "member";
  const personId = str(f, "person_id") ? Number(str(f, "person_id")) : null;
  let timezone = str(f, "timezone");
  if (!TZ.has(timezone)) {
    const { data } = personId ? await supabase.from("people").select("country").eq("id", personId).maybeSingle() : { data: null };
    timezone = COUNTRY_TZ[data?.country ?? "CO"];
  }
  const { error } = await supabase.from("users").upsert(
    { email, role, person_id: personId, timezone, active: true }, { onConflict: "email" });
  done(error);
}

export async function cambiarActivo(email: string, active: boolean) {
  const supabase = await db();
  const { error } = await supabase.from("users").update({ active }).eq("email", email);
  done(error);
}

export async function guardarPersona(f: FormData) {
  const supabase = await db();
  const id = str(f, "id") ? Number(str(f, "id")) : null;
  const country = str(f, "country") === "CR" ? "CR" : "CO";
  const slack = str(f, "slack_user_id") || null;
  if (slack && !/^[UW][A-Z0-9]{6,}$/.test(slack)) throw new Error("El Slack user ID empieza con U y tiene letras mayúsculas y números.");
  const name = str(f, "name");
  if (!id && !name) throw new Error("Falta el nombre.");
  const { error } = id
    ? await supabase.from("people").update({ country, slack_user_id: slack, ...(name ? { name } : {}) }).eq("id", id)
    : await supabase.from("people").insert({ name, code: str(f, "code").toUpperCase() || null, country, slack_user_id: slack });
  done(error);
}

export async function agregarPto(f: FormData) {
  const supabase = await db();
  const day = str(f, "day");
  if (!DAY.test(day)) throw new Error("Fecha no válida.");
  const { error } = await supabase.from("pto").upsert(
    { person_id: Number(str(f, "person_id")), day, origin: "app" }, { onConflict: "person_id,day" });
  done(error);
}

export async function quitarPto(personId: number, day: string) {
  const supabase = await db();
  const { error } = await supabase.from("pto").delete().eq("person_id", personId).eq("day", day);
  done(error);
}

export async function agregarDiaForte(f: FormData) {
  const supabase = await db();
  const day = str(f, "day");
  const name = str(f, "name");
  if (!DAY.test(day) || !name) throw new Error("Falta la fecha o el motivo.");
  // created_by lo pone la base con el correo del token.
  const { error } = await supabase.from("forte_non_working_days").upsert({ day, name }, { onConflict: "day" });
  done(error);
}

export async function quitarDiaForte(day: string) {
  const supabase = await db();
  const { error } = await supabase.from("forte_non_working_days").delete().eq("day", day);
  done(error);
}
