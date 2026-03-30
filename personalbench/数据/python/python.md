#### python

##### 标准数据类型

不可变：Number、String、Tuple

可变：List、Set、Dictionary

###### Number

int、float、bool、complex

数学函数

<img src="E:\笔记\python\数学函数.jpeg" style="zoom:80%;" />

###### String

\ 用来转义，r去除 \ 的转义效果

<img src="E:\笔记\python\字符串的内置函数.jpeg" style="zoom:80%;" />

###### List

列表使用[]括起来，元素之间以，分割

访问列表：从左开始为0，从右开始为-1

``` 
list.append() #在末尾添加元素
list.count() #统计元素出现的次数
list.extend(seq) #扩展序列
list.index() #查询某个元素第一次出现的索引位置
list.insert(index,obj) #在当前索引处插入元素
list.pop([index=-1]) #移出元素，默认最后一位
list.remove(obj) #移除列表中的第一个匹配项
list.sort() #对列表进行排序
list.clear() #清除列表
list.copy() #复制列表
del list[1] #删除元素
len(list) #列表的长度
max(list) #列表的最大值
min(list) #列表的最小值
list(seq) #将元组转化为列表
```

列表推导式

```
[表达式 for 变量 in 列表] 
[out_exp_res for out_exp in input_list]
或者 
[表达式 for 变量 in 列表 if 条件]
[out_exp_res for out_exp in input_list if condition]
```

###### Tuple

元组使用()括起来，元素之间以，分割（只有一个元素的元组，元素后面要加，）

```
del Tuple #删除元组
len(Tuple) #元组的长度
max(Tuple) #元组的最大值
min(Tuple) #元组的最小值
Tuple(iterable) #将可迭代系列转化为元组
```

元组推导式

```
(expression for item in Sequence )
或
(expression for item in Sequence if conditional )
```

###### Set

集合是无序、可变的数据类型，用于存储不重复的数据。集合使用{}表示，元素之间使用，分割

创建空的集合使用set()，而不是{}

```
set.add() #添加元素
set.remove() #移除元素，元素不存在会发生错误
set.discard() #移除元素，元素不存在不会发生错误
set.pop() #随机删除元素
len(set) #集合的元素个数
set.clear() #清空集合
```

集合推导式

```
{ expression for item in Sequence }
或
{ expression for item in Sequence if conditional }
```

###### Dict

key使用不可变类型，且唯一

<img src="C:\Users\86188\AppData\Roaming\Typora\typora-user-images\image-20250512201839504.png" alt="image-20250512201839504" style="zoom:80%;" />

<img src="E:\笔记\python\字典内置函数.jpeg" style="zoom:80%;" />

字典推导式

```
{ key_expr: value_expr for value in collection }

或

{ key_expr: value_expr for value in collection if condition }
```

遍历字典（items）

```
>>> knights = {'gallahad': 'the pure', 'robin': 'the brave'}
>>> for k, v in knights.items():
...     print(k, v)
...
gallahad the pure
robin the brave
```

内置函数type、isinstance（isinstance认为子类和父类是相同类型，type则相反）可以查看数据类型

<img src="E:\笔记\python\数据类型转化.jpeg" style="zoom:80%;" />

##### 注释

```
# 单行注释
""" """ 或者 ''' ''' 多行注释
```

##### 保留字

<img src="E:\笔记\python\保留字.jpeg" style="zoom: 80%;" />



##### 运算符

###### 算数运算符

```
+ 加法
- 减法
* 乘法（字符串相乘得到多个重复的字符串）
/ 除法
% 取模
** 幂次
// 向下取整
```

###### 比较运算符

```
== 等号
！= 不等号
< 小于号
> 大于号
```

###### 赋值运算符

```
= 赋值
+= 加法赋值
-= 加法赋值
*= 乘法赋值
/= 除法赋值
%= 取模赋值
**= 幂运算赋值
//= 整除赋值
```

###### 位运算符

```
& 按位与：全为1为1，否则为0
| 按位或：有一个为1为1，否则为0
^ 按位异或：相异为1
~ 按位取反：0变1，1变0
<< 左移运算符：最高位超出数据范围的丢弃，低位补0
>> 右移运算符
```

###### 逻辑运算符

```
and 全为真为真
or 部分为真为真
not 非
```

###### 成员运算符

```
in
not in
```

###### 身份运算符

```
is
is not
```

##### 条件控制

```
嵌套语句
if 表达式1:
    语句
    if 表达式2:
        语句
    elif 表达式3:
        语句
    else:
        语句
elif 表达式4:
    语句
else:
    语句
```

match...case

```
def http_error(status):
    match status:
        case 400:
            return "Bad request"
        case 404:
            return "Not found"
        case 418:
            return "I'm a teapot"
        case _:
            return "Something's wrong with the internet"

mystatus=400
print(http_error(400))
```

##### 循环语句

###### while

```
n = 100
 
sum = 0
counter = 1
while counter <= n:
    sum = sum + counter
    counter += 1
 
print("1 到 %d 之和为: %d" % (n,sum))
```

while循环使用else语句，当while语句为false时执行else语句

for ... else 当for循环结束时执行else语句

##### 函数

###### 参数传递

在python中，类型属于对象，对象有不同的类型区分，变量是没有类型的。

不可变类型：传递的只是a的值，当修改a时会生成新的对象

可变类型：将a对象传递过去，修改会影响a本身

必须参数；关键字参数；默认参数(当无参数传递时取默认值)；不定长参数（*代表元组，**代表字典）

###### 匿名函数

Python 中使用lambda创建匿名函数，lambda 函数拥有自己的命名空间，且不能访问自己参数列表之外或全局命名空间里的参数。

##### 装饰器

###### 应用场景

- **日志记录**: 装饰器可用于记录函数的调用信息、参数和返回值；
- **性能分析**: 可以使用装饰器来测量函数的执行时间；
- **权限控制**: 装饰器可用于限制对某些函数的访问权限；
- **缓存**: 装饰器可用于实现函数结果的缓存，以提高性能。

```
def decorator_function(original_function):
    def wrapper(*args, **kwargs):
        # 这里是在调用原始函数前添加的新功能
        before_call_code()
        
        result = original_function(*args, **kwargs)
        
        # 这里是在调用原始函数后添加的新功能
        after_call_code()
        
        return result
    return wrapper

# 使用装饰器
@decorator_function
def target_function(arg1, arg2):
    pass  # 原始函数的实现
```

- 当我们使用 `@decorator_function` 前缀在 `target_function` 定义前，Python会自动将 `target_function` 作为参数传递给 `decorator_function`，然后将返回的 `wrapper` 函数替换掉原来的 `target_function`。

###### 当参数的装饰器

如果原函数需要参数，可以在装饰器的 wrapper 函数中传递参数：

```
def my_decorator(func):
    def wrapper(*args, **kwargs):
        print("在原函数之前执行")
        func(*args, **kwargs)
        print("在原函数之后执行")
    return wrapper

@my_decorator
def greet(name):
    print(f"Hello, {name}!")

greet("Alice")
```

装饰器本身也可以接受参数，此时需要额外定义一个外层函数：

```
def repeat(num_times):
    def decorator(func):
        def wrapper(*args, **kwargs):
            for _ in range(num_times):
                func(*args, **kwargs)
        return wrapper
    return decorator

@repeat(3)
def say_hello():
    print("Hello!")

say_hello()
```

##### 数据结构

将列表作为栈使用

队列：collections.duque

```
from collections import deque

# 创建一个空队列
queue = deque()

# 向队尾添加元素
queue.append('a')
queue.append('b')
queue.append('c')

print("队列状态:", queue)  # 输出: 队列状态: deque(['a', 'b', 'c'])

# 从队首移除元素
first_element = queue.popleft()
print("移除的元素:", first_element)  # 输出: 移除的元素: a
print("队列状态:", queue)            # 输出: 队列状态: deque(['b', 'c'])

# 查看队首元素（不移除）
front_element = queue[0]
print("队首元素:", front_element)    # 输出: 队首元素: b

# 检查队列是否为空
is_empty = len(queue) == 0
print("队列是否为空:", is_empty)     # 输出: 队列是否为空: False

# 获取队列大小
size = len(queue)
print("队列大小:", size)            # 输出: 队列大小: 2
```

##### 模块

```
import module 导入整个模块
from module import def 导入函数
```

__name__属性

- 如果模块是被直接运行，`__name__` 的值为 `__main__`。
- 如果模块是被导入的，`__name__` 的值为模块名。

##### 输入和输出

输出格式

``` 
rjust(n)  #输出靠右，占n个空格
ljust(n)  #输出靠左，占n个空格
center(n) #居中输出，占n个空格
zfill(n)  #左边填充0
```

