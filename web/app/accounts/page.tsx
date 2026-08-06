import { getAccounts, type Account } from "@/lib/accounts";

// 不同 status → 不同颜色标签。Record<string,string> = 「键值都是字符串」的对象类型
const STATUS_STYLES: Record<string, string> = {
  active: "bg-green-100 text-green-800",
  offline: "bg-gray-100 text-gray-600",
  new: "bg-blue-100 text-blue-800",
  error: "bg-red-100 text-red-800",
};

export default async function AccountsPage() {
  // 服务端取数。现在 getAccounts() 返回 mock；接后端时这里一行不改。
  const accounts = await getAccounts();

  // 注意：用 <section> 不用 <main>，因为 <main> 通常由根布局 layout.tsx 提供，
  // 避免和 Slice 1a 你在 layout 里写的 <main> 嵌套重复。
  return (
    <section className="p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">账号管理</h1>
        <p className="text-sm text-gray-500 mt-1">
          共 {accounts.length} 个账号 · mock 数据（接后端后自动换真实数据）
        </p>
      </header>

      {/* 账号列表：用 table 展示。
          A2 会在表格上方加一个搜索框（Client Component），客户端筛选这份数据。 */}
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="text-left border-b">
            <th className="py-2 pr-4">脱敏号码</th>
            <th className="py-2 pr-4">用户名</th>
            <th className="py-2 pr-4">状态</th>
            <th className="py-2 pr-4">最后登录</th>
          </tr>
        </thead>
        <tbody>
          {accounts.map((a: Account) => (
            // React 列表要求每个元素有稳定、唯一的 key —— 用账号 id 最合适
            <tr key={a.id} className="border-b hover:bg-gray-50">
              <td className="py-2 pr-4 font-mono">{a.phoneMasked}</td>

              <td className="py-2 pr-4">
                {/* username 可能为空：有则 @xxx，无则占位 */}
                {a.username ? (
                  `@${a.username}`
                ) : (
                  <span className="text-gray-400">—</span>
                )}
              </td>

              <td className="py-2 pr-4">
                {/* 状态标签：未知 status 回退到灰色（?? 是「空值合并」运算符） */}
                <span
                  className={`px-2 py-0.5 rounded text-xs ${
                    STATUS_STYLES[a.status] ?? "bg-gray-100 text-gray-600"
                  }`}
                >
                  {a.status}
                </span>
              </td>

              <td className="py-2 pr-4 text-gray-600">
                {/* lastLoginAt 为 null = 从未登录 */}
                {a.lastLoginAt ?? (
                  <span className="text-gray-400">从未登录</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}