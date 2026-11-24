/** 中文界面文案。扁平 key，`component.purpose`。
 *
 * 2228 条按 key 前缀拆到 `./zh/*`（8)，这里按原序合并；查表语义与拆分前一致。
 */

import { zh_entry } from "./zh/entry";
import { zh_studio } from "./zh/studio";
import { zh_settings } from "./zh/settings";
import { zh_settings2 } from "./zh/settings2";
import { zh_stmt } from "./zh/stmt";
import { zh_debts } from "./zh/debts";
import { zh_connect } from "./zh/connect";
import { zh_tax } from "./zh/tax";
import { zh_review } from "./zh/review";
import { zh_plan } from "./zh/plan";
import { zh_external } from "./zh/external";
import { zh_autopilot } from "./zh/autopilot";
import { zh_ecommerce } from "./zh/autopilot";

export const zh: Record<string, string> = {
  ...zh_entry,
  ...zh_studio,
  ...zh_settings,
  ...zh_settings2,
  ...zh_stmt,
  ...zh_debts,
  ...zh_connect,
  ...zh_tax,
  ...zh_review,
  ...zh_plan,
  ...zh_external,
  ...zh_autopilot,
  ...zh_ecommerce,
};
