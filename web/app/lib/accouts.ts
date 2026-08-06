import { types } from "util";

export type Account = {
    id: number;               // 主键：列表 key + 未来详情页路由参数 /accounts/[id]
  phoneMasked: string;      // 脱敏号码（后端 phone_masked），如 "+1 555 •••• 42"
  userId: number | null;    // Telegram user id；null = 账号还没登录绑定
  username: string | null;  // @用户名；可为空
  firstName: string | null; // 名
  lastName: string | null;  // 姓
  status: string;           // 状态（真实枚举值接后端时以后端为准；这里用 active/offline/new/error）
  lastLoginAt: string | null; // 最后登录时间 ISO 字符串；null = 从未登录
} 

export async function getAccounts(): Promise<Account[]> {
    //TODO:等待伺服器端的服務編寫 mock 數據
    return [
        {
      id: 1,
      phoneMasked: "+1 555 •••• 42",
      userId: 700000001,
      username: "alpha_ops",
      firstName: "Alpha",
      lastName: null,
      status: "active",
      lastLoginAt: "2026-08-05T12:30:00Z",
    },
    {
      id: 2,
      phoneMasked: "+44 7700 •••• 18",
      userId: 700000002,
      username: null,
      firstName: "Beta",
      lastName: "Team",
      status: "offline",
      lastLoginAt: "2026-08-01T09:10:00Z",
    },
    {
      id: 3,
      phoneMasked: "+55 11 9•••• 77",
      userId: null, // 还没登录绑定
      username: null,
      firstName: null,
      lastName: null,
      status: "new",
      lastLoginAt: null, // 从未登录
    },
    {
      id: 4,
      phoneMasked: "+1 555 •••• 03",
      userId: 700000004,
      username: "delta_support",
      firstName: "Delta",
      lastName: "Ops",
      status: "error",
      lastLoginAt: "2026-07-28T18:45:00Z",
    },
    ]
}