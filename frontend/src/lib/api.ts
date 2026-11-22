/** API 访问层门面：按域拆到 `./api/*`，这里只做汇总转出（`export *`）。
 *
 * 调用方一律 `from "@/lib/api"` 或 `from "../lib/api"`，无需改路径。
 */

export * from "./api/client";
export * from "./api/personal";
export * from "./api/family";
export * from "./api/gl";
export * from "./api/banking";
export * from "./api/procurement";
export * from "./api/longtask";
export * from "./api/history";

export * from "./api/remote";
