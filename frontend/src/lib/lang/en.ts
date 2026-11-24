/** English UI strings. Flat keys, `component.purpose`.
 *
 * Split into `./en/*` by key prefix (8 groups); merged here in the original order.
 */

import { en_entry } from "./en/entry";
import { en_studio } from "./en/studio";
import { en_settings } from "./en/settings";
import { en_settings2 } from "./en/settings2";
import { en_stmt } from "./en/stmt";
import { en_debts } from "./en/debts";
import { en_connect } from "./en/connect";
import { en_tax } from "./en/tax";
import { en_review } from "./en/review";
import { en_plan } from "./en/plan";

export const en: Record<string, string> = {
  ...en_entry,
  ...en_studio,
  ...en_settings,
  ...en_settings2,
  ...en_stmt,
  ...en_debts,
  ...en_connect,
  ...en_tax,
  ...en_review,
  ...en_plan,
};
