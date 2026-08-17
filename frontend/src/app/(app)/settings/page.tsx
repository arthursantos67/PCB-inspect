import { redirect } from "next/navigation";

/** Settings has no landing page of its own — the sidebar's "Settings" entry points at the
 * section, so it lands on the section's first tab instead of a 404.
 */
export default function SettingsIndexPage() {
  redirect("/settings/accounts");
}
