## DHCP部署与安全

------

DHCP（dynamic host configure protocol）用于自动分配IP地址

地址池/作用域（IP、子网掩码、网关、DNS、租期）

DHCP原理

```
1、客户机发送DHCP Discovery广播包（客户机广播请求IP地址，包括mac地址）
2、服务器响应DHCP Offer广播包
3、客户机发送DHCP Request广播包（客户机选择IP）（续约）
4、服务器发送DHCP ACK广播包（服务器确定租约，并提供网卡等详细参数）
5、DHCP续约
```

当无任何服务器响应时，网卡自己分配一个169.254.x.x/16

ipconfig /release 释放IP（取消租约，或者改为手动配置IP）

ipconfig /renew重新获取IP（有IP时，发送request续约，无IP时发送Discovery）

地址保留

```
对于指定的MAC地址，固定动态分配的IP地址
```

