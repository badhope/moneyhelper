import { useQuery } from "@tanstack/react-query";
import { getMyCapabilities } from "@/lib/api";

/**
 * 当前用户在当前工作租户里的权限点（切片 7a）。
 *
 * 后端 `GET /api/org/capabilities` 与真实放行判定同源；前端只用来隐藏/禁用
 * 写入口，不能把它当安全边界——真正的拒绝仍在 API。
 */
export function useCapabilities() {
  const q = useQuery({
    queryKey: ["my-capabilities"],
    queryFn: getMyCapabilities,
    staleTime: 0,
    refetchOnMount: "always",
  });
  const permissions = new Set(q.data?.permissions ?? []);
  return {
    role: q.data?.role ?? "",
    permissions,
    loading: q.isLoading,
    can: (permission: string) => permissions.has(permission),
  };
}
