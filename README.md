# 光谱波长校准台

校准员提交标称波长与实测波长。独立领取进程按允差写出合格或超差。页面轮询直到结论出现。

## 端口

| 服务 | 地址 |
|------|------|
| 页面 | http://localhost:3195 |
| 接口 | http://localhost:8195 |
| PostgreSQL | localhost:54395 |

## 账号

| 用户 | 密码 | 权限 |
|------|------|------|
| calibrator | calib123456 | 可提交校准、可在署名台改派在途单 |
| inspector | insp123456 | 只看(署名与履历可读,不可改派) |

## 署名台

领取进程把新单切入「领取中」时落下领取名(worker-a/b/c),结案后署名保留。
导航「署名台」专页提供:

- 在途改派说明;
- 按领取人筛选的已署名清单与改派履历;
- 按灯种核对署名与领取进程是否一致;
- 校准员可把在途单改派另一领取名(记入履历),已结案单不可改派。

接口:`GET /api/signature-desk`(支持 `claim_name`、`lamp` 查询参数)、`POST /api/jobs/{id}/reassign`。

## 启动

```bash
cd projects/16-spectrum-wavelength-desk
docker compose up --build
```

## 验收

1. calibrator 登录后,种子「氦灯-587」合格、「汞灯-546」超差,署名为 worker-a。
2. 再提交超差样条,先待处理,再「领取中」落领取名(署名台可见),结案后署名保留。
3. 领取中的在途单改派 worker-b,结案后署名换成 worker-b,履历留下改派痕迹;已结案单改派被拒。
4. inspector 不能提交、不能改派,可读署名与履历。
