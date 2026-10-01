"use client";
import { createClient } from "@/lib/supabase/client";

export function GoogleButton() {
  async function signIn() {
    const supabase = createClient();
    await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
        // hd solo sugiere la cuenta de Forte en la pantalla de Google. No protege nada:
        // el dominio lo valida la base y el hook de registro.
        queryParams: { hd: "forteglobal.com", prompt: "select_account" },
      },
    });
  }
  return (
    <button className="primary" onClick={signIn}>
      Entrar con Google
    </button>
  );
}
