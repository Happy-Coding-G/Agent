#### Mysql

##### DDL-数据库操作

###### 查看数据库

```
show databases;
```

###### 使用数据库

```
use 数据库;
```

###### 创建数据库

```
create database [if not exists] 数据库名;
```

###### 删除数据库

```
drop database 数据库；
```

##### DDL-表操作

###### 查询当前数据库的所有表

```
show tables;
```

###### 查询表结构

```
desc 表名；
```

###### 查询指定表的建表语句

```
show create table 表名；
```

###### 表中添加字段

```
alter table 表名 add 字段名 类型 [comment 注释] 约束；
```

###### 修改数据类型

```
alter table 表名 modify 字段名 新数据类型 [comment 注释] 约束；
```

###### 修改字段名和数据类型

```
alter table 表名 change 旧字段名 新字段名 类型 [comment 注释] 约束；
```

###### 删除字段

```
alter table 表名 drop 字段名；
```

###### 删除表

```
DROP TABLE table_name；#表名为数字时，需要加反引号
```

###### 删除表中的数据

```
DELETE FROM table_name where 条件；
TRUNCATE TABLE table_name；#清空表
```

##### DML-插入

###### 添加数据

```
insert into 表名 （字段1，字段2，...） values （字段1，字段2，...）; 
insert into 表名 values （字段1，字段2，...）; #全部字段
insert into 表名 （字段1，字段2，...） values （字段1，字段2，...），（字段1，字段2，...）...;  #批量添加
```

###### 修改数据

```
update 表名 set 字段1=值1，字段2=值2,... where 条件；
```

###### 删除数据

```
delete from 表名 where 条件；
```

##### DQL-查询

###### 查询数据

```
select 字段名 from 表名 where 条件；
```

###### 查询条件

```
between ... and ...  #在某个范围之间
in ...  #在in之后的列表中的值
like ... #模糊匹配（_匹配单个字符，%匹配任意字符）
is null  #是null
```

###### 聚合函数

```
select 聚合函数（字段名） from 表名；（null不参与计算）
count 统计数量；max 最大值；min 最小值；avg 平均值；sum 和；
```

###### 分组查询

```
select 字段名 from 表名 where 条件 group by 分组字段名 having 分组后的过滤条件；
```

###### 排序查询

```
select 字段名 fron 表名 order by 字段1 排序方式，字段2，排序方式；
```

###### 分页查询

```
select 字段名 fron 表名 limit 起始索引，查询记录数；
```

##### DCL-管理用户

###### 查询用户

```
use mysql;
select * from user;
```

###### 创建用户

```
create user '用户名'@'主机名' identified by '密码';
```

###### 修改用户密码

```
alter user '用户名'@'主机名' identified with mysql_native_password by '新密码';
```

###### 删除用户

```
drop user '用户名'@'主机名';
```

###### 查询权限

```
show grants for '用户名'@'主机名';
```

###### 授予权限

```
grant 权限列表 on 数据库名.表名 to '用户名'@'主机名';
```

###### 撤销权限

```
revoke 权限列表 on 数据库名.表名 to '用户名'@'主机名';
```

##### 函数

###### 字符串函数

```
concat(s1,s2...) #拼接字符串
lower(str) #将字符串全部小写
upper(str) #将字符串全部大写
lpad(str,n,pad) #左填充，用字符串pad对str进行左填充，直到n个字符
rpad(str,n,pad) #右填充，用字符串pad对str进行右填充，直到n个字符
trim(str) #去掉字符串头部和尾部的空格
substring(str,start,len) #返回字符串str中从start位置起len个字符
```

###### 数值函数

```
ceil(x) #向上取整
floor(x) #向下取整
mod(x,y) #返回x/y的模
rand(x) #返回0-1的随机数
round(x,y) #求x四舍五入的值，保留y位小数
```

###### 日期函数

```
curdate() #返回当前日期
curtime() #返回当前时间
now() #返回当前日期和时间
year(date) #获取指定date的年份
month(date) #获取指定date的月份
day(date) #获取指定date的日期
date_add(date,interval expr type) #返回一个日期加上一个时间间隔expr后的时间值
datediff(date1,date2) #返回date1和date2之间的天数
```

###### 流程函数

```
if(value,t,f) #如果value为true，返回t，否则返回f
ifnull(value1,value2) #如果value1不为空，返回value，否则返回value2
case expr when val1 then res1 ... else default end #如果val1为true，返回res1，...否则返回default默认值
```

##### 约束

![image-20250715094831924](C:\Users\86188\AppData\Roaming\Typora\typora-user-images\image-20250715094831924.png)

##### 多表查询

###### 内连接

```
select 字段列表 from 表1，表2 where 条件； #隐式内连接
select 字段列表 from 表1 inner join 表2 on 连接条件； #显式内连接
```

###### 外连接

```
select 字段列表 from 表1 left [outer] join 表2 on 连接条件； #左外连接
select 字段列表 from 表1 right [outer] join 表2 on 连接条件； #右外连接
```

###### 自连接

```
select 字段列表 from 表1 别名1 join 表1 别名2 on 连接条件； #可以将一个表看作两个表，转变为内连接或外连接
```

###### 联合查询

```
select 字段列表 from 表1 union [all] select 字段列表 from 表2；
```

###### 子查询

```
select 字段列表 from 表1 where column1 = (select column1 from 表2)；
```

##### 存储引擎

###### 创建表时指定存储引擎

```
engine=InnoDB
```

###### 查看当前数据库支持的存储引擎

```
show engines；
```

##### 索引

###### 创建索引

```
create [unique|fulltext] index index_name on table_name (index_col_name,...);
```

###### 查看索引

```
show index from table_name;
```

###### 删除索引

```
drop index index_name on table_name;
```

###### 查看数据库的访问频率

```
show global status like 'Com_______';
```

###### 性能分析-profile

```
select @@have_profiling;  # 查看是否支持profile
set profiling = 1;  # 开启profile 
show profiles;  # 查看每一条SQL的耗时情况
show profile for query query_id;  # 查看指定query_id的SQL语句各个阶段的执行情况
show profile cpu for query query_id;  # 查看指定query_id的SQL语句cpu的执行情况
```

###### 性能分析-explain

```
explain SQL语句;  # 解释语句执行过程
```

###### 索引使用

```
最左前缀法则：查询从索引的最左列开始，并且不跳过索引中的列；
不要在索引列上进行运算操作，索引会失效；
字符串类型字段使用时，不加引号，索引会失效；
尾部模糊匹配，索引不会失效；头部模糊匹配，索引会失效；
用or分割开的条件，需要前后均包含索引；
Mysql评估索引比全表更慢，则不使用索引
```

###### SQL提示

```
use index(索引名)  # 使用索引
ignore index(索引名)  # 忽略索引
force index(索引名)  # 强制索引
```

