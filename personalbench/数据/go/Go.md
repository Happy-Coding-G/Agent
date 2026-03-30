##### Go 语法基础

###### 基本语法

可见性控制

- 名称大写字母开头，即为公有类型/变量/常量
- 名字小写或下划线开头，即为私有类型/变量/常量

包内名为`internal`包为内部包，外部包将无法访问内部包中的任何内容

###### 输入输出

- `os.Stdin` - 标准输入
- `os.Stdout` - 标准输出
- `os.Stderr` - 标准错误

输出

stdout

```go
package main

import "os"

func main() {
  os.Stdout.WriteString("hello world!")
}
```

fmt

```
package main

import "fmt"

func main() {
  fmt.Println("hello world!")
}
```

bufio

```
func main() {
  writer := bufio.NewWriter(os.Stdout)
  defer writer.Flush()
  writer.WriteString("hello world!")
}
```

输入

fmt

```
// 扫描从os.Stdin读入的文本，根据空格分隔，换行也被当作空格
func Scan(a ...any) (n int, err error)

// 与Scan类似，但是遇到换行停止扫描
func Scanln(a ...any) (n int, err error)

// 根据格式化的字符串扫描
func Scanf(format string, a ...any) (n int, err error)
```

bufio

```
func main() {
    reader := bufio.NewReader(os.Stdin)
    var a, b int
    fmt.Fscanln(reader, &a, &b)
    fmt.Printf("%d + %d = %d\n", a, b, a+b)
}
```

scanner

```
func main() {
  scanner := bufio.NewScanner(os.Stdin)
  for scanner.Scan() {
    line := scanner.Text()
    if line == "exit" {
      break
    }
    fmt.Println("scan", line)
  }
}
```

###### 数组

数组的初始化

```
var a [3]int = [3]int{1, 2, 3} // 使用一组值来初始化数组，默认值为0
a := [...]int{1, 2, 3} // 出现...时数组的长度由初始化值的个数来决定
```

两个数组的类型相同（数组的长度、元素的类型），可以使用==和！=判断数组是否相等。

多维数组的初始化

```
// 声明一个二维整型数组，两个维度的长度分别是 4 和 2
var array [4][2]int
// 使用数组字面量来声明并初始化一个二维整型数组
array = [4][2]int{{10, 11}, {20, 21}, {30, 31}, {40, 41}}
// 声明并初始化数组中索引为 1 和 3 的元素
array = [4][2]int{1: {20, 21}, 3: {40, 41}}
// 声明并初始化数组中指定的元素
array = [4][2]int{1: {0: 20}, 3: {1: 41}}
```

###### 切片

从数组或切片生成新的切片拥有如下特性：

- 取出的元素数量为：结束位置 - 开始位置；
- 取出元素不包含结束位置对应的索引，切片最后一个元素使用 slice[len(slice)] 获取；
- 当缺省开始位置时，表示从连续区域开头到结束位置；
- 当缺省结束位置时，表示从开始位置到整个连续区域末尾；
- 两者同时缺省时，与切片本身等效；
- 两者同时为 0 时，等效于空切片，一般用于切片复位。

初始化

```
var nums []int // 值
nums := []int{1, 2, 3} // 值
nums := make([]int, 0, 0) // 值
nums := new([]int) // 指针
```

切片复制

```
copy( destSlice, srcSlice []T) int // srcSlice 为数据来源切片，destSlice 为复制的目标（也就是将 srcSlice 复制到 destSlice）
```

插入元素

```
nums := []int{1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
从头部插入
nums = append([]int{-1, 0}, nums...)
从中间下标i插入元素
nums = append(nums[:i+1], append([]int{999, 999}, nums[i+1:]...)...)
从尾部插入
nums = append(nums, 99, 100)
```

从开头删除元素

```
原理：通过切片表达式直接从索引N开始创建新切片，新切片与原切片共享底层数组，但起始指针指向原切片的第N个元素。
数据指针行为：
原切片底层数组的数据未发生任何移动，只是切片的start指针（指向底层数组的起始位置）从0变为N。
新切片的长度为len(a)-N，容量为cap(a)-N（仍共享原底层数组）。
a = []int{1, 2, 3}
a = a[1:] // 删除开头1个元素
a = a[N:] // 删除开头N个元素
```

```
原理：先创建一个长度为 0 的空切片（a[:0]，仍指向原底层数组的起始位置），再将a[N:]的元素追加到这个空切片中，相当于把剩余元素 “前移” 到切片头部。
数据指针行为：
底层数组的数据发生了移动：a[N:]的元素会被复制到原切片的头部（从索引0开始覆盖）。
新切片的start指针仍指向底层数组的0位置，但元素已被新数据覆盖。
a = []int{1, 2, 3}
a = append(a[:0], a[1:]...) // 删除开头1个元素
a = append(a[:0], a[N:]...) // 删除开头N个元素
```

```
a = []int{1, 2, 3}
a = a[:copy(a, a[1:])] // 删除开头1个元素
a = a[:copy(a, a[N:])] // 删除开头N个元素
```

```
nums := []int{1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
从尾部删除n个元素
nums = nums[:len(nums)-n]
从中间指定下标删除n个元素
nums = append(nums[:i], nums[i+n:]...)
```

多维切片初始化

```
slices := make([][]int, 5)
for i := 0; i < len(slices); i++ {
   slices[i] = make([]int, 5)
}slices := make([][]int, 5)
for i := 0; i < len(slices); i++ {
   slices[i] = make([]int, 5)
}
```

与字符串的转换

```
func main() {
   str := "this is a string"
   // 显式类型转换为字节切片
   bytes := []byte(str)
   fmt.Println(bytes)
   // 显式类型转换为字符串
   fmt.Println(string(bytes))
}
```

###### 映射表

初始化

```
mp := map[int]string{
   0: "a",
   1: "a",
   2: "a",
   3: "a",
   4: "a",
}

mp := map[string]int{
   "a": 0,
   "b": 22,
   "c": 33,
}

mp := make(map[string]int, 8)

mp := make(map[string][]int, 10)
```

删除

```
delete(map, key)
```

sync.Map（支持并发读写）

```
package main

import (
	"fmt"
	"sync"
	"time"
)

func main() {
	var m sync.Map

	// 启动 5 个 goroutine 写入数据
	for i := 0; i < 5; i++ {
		go func(id int) {
			key := fmt.Sprintf("key%d", id)
			m.Store(key, id) // 存储键值对
			fmt.Printf("写入: %s -> %d\n", key, id)
		}(i)
	}

	// 等待写入完成（实际开发中需用 sync.WaitGroup）
	time.Sleep(100 * time.Millisecond)

	// 遍历所有键值对
	fmt.Println("\n遍历结果:")
	m.Range(func(key, value interface{}) bool {
		fmt.Printf("%s -> %d\n", key, value)
		return true // 继续遍历
	})

	// 读取一个键
	if val, ok := m.Load("key2"); ok {
		fmt.Printf("\n读取 key2: %d\n", val)
	}

	// 删除一个键
	m.Delete("key3")
	fmt.Println("\n删除 key3 后:")
	if _, ok := m.Load("key3"); !ok {
		fmt.Println("key3 已不存在")
	}
}

```

list（列表，等价于双向链表）

```
package main

import (
	"container/list"
	"fmt"
)

func main() {
	l := list.New() // 创建一个新的双向链表

	// 在尾部插入元素（类似 append）
	l.PushBack(1)
	l.PushBack(2)

	// 在头部插入元素
	l.PushFront(0)

	// 遍历链表（从头到尾）
	for e := l.Front(); e != nil; e = e.Next() {
		fmt.Printf("%v ", e.Value) // 输出：0 1 2
	}
	fmt.Println()

	// 在元素 1 之后插入 1.5
	mid := l.Front().Next() // 获取值为 1 的节点
	l.InsertAfter(1.5, mid)

	// 再次遍历
	for e := l.Front(); e != nil; e = e.Next() {
		fmt.Printf("%v ", e.Value) // 输出：0 1 1.5 2
	}
}

```

##### Go语法进阶

###### 接口

方法：类似于函数，存在接收者，只有自定义类型能够拥有方法；接收者明确了该方法属于哪种类型，使得方法称为类型的“成员行为”；不同类型可以有同名的方法，靠接收者类型进行区分；方法必须通过类型实例调用；值接收者、指针接收者

- 基本接口(`Basic Interface`)：**只包含方法集**的接口就是基本接口
- 通用接口(`General Interface`)：**只要包含类型集**的接口就是通用接口

基本接口

```
声明
type Person interface {
  Say(string) string
  Walk(int)
}
```

接口的实现是隐式的，只要是实现了一个接口的全部方法，那就是实现了该接口。

空接口

```
type Any interface{

}
```

###### 泛型（参数化多态）

类型形参：T , 形参是什么类型，取决于传入的是什么类型；

类型约束：int | float64 ，规定了哪些类型是允许的；

**类型实参**：`Sum[int](1,2)`，手动指定了 `int` 类型，`int` 就是类型实参。

```
func Sum[T int | float64](a, b T) T {
   return a + b
}
```

泛型切片

```
type GenericSlice[T int | int32 | int64] []T
GenericSlice[int]{1, 2, 3}（使用时不能忽略掉类型实参）
```

泛型哈希表（键的类型必须是可比较的，所以使用 `comparable` 接口，值的类型约束为 `V int | string | byte`）

```
type GenericMap[K comparable, V int | string | byte] map[K]V
gmap1 := GenericMap[int, string]{1: "hello world"}
gmap2 := make(GenericMap[string, byte], 0)
```

泛型结构体

```
type GenericStruct[T int | string] struct {
   Name string
   Id   T
}
```

泛型接口

```
type SayAble[T int | string] interface {
   Say() T
}

type Person[T int | string] struct {
   msg T
}

func (p Person[T]) Say() T {
   return p.msg
}

func main() {
  var s SayAble[string]
  s = Person[string]{"hello world"}
  fmt.Println(s.Say())
}
```

**类型断言（Type Assertion）** 是一种用于**从接口类型变量中提取底层具体类型值**的操作。核心作用是：当你知道一个接口变量绑定了某个具体类型的值时，可以通过类型断言将接口变量 "还原" 为该具体类型，从而访问其特有方法或字段。

基本语法

```
不带判断的形式：
具体类型变量 := 接口变量.(具体类型)
带判断的形式：
具体类型变量, 布尔值 := 接口变量.(具体类型)
```

断言函数

```
func Assert[T any](v any) (bool, T) { // T 函数的类型参数，v 传入的参数
	var av T  // av 初始化为T类型的零值，用于存储断言的结果。如果断言成功（v 确实是 T 类型），则会被赋值为 v 转换为 T 类型后的值；如果断言失败（v 不是 T 类型或 v 为 nil），则保持 T 类型的零值，并作为函数的第二个返回值返回。
	if v == nil {
		return false, av
	}
	av, ok := v.(T)
	return ok, av
}

func main() {
    var x any = "hello"
    
    // 尝试将 x 转换为 string 类型
    ok, str := Assert[string](x)
    if ok {
        fmt.Println("转换成功:", str) // 输出: 转换成功: hello
    }
    
    // 尝试将 x 转换为 int 类型
    ok, num := Assert[int](x)
    if !ok {
        fmt.Println("转换失败，得到的零值是:", num) // 输出: 转换失败，得到的零值是: 0
    }
}
```

类型数据集

并集

```
type SignedInt interface {
  int8 | int16 | int | int32 | int64
}

type UnSignedInt interface {
  uint8 | uint16 | uint32 | uint64
}

type Integer interface {
  SignedInt | UnSignedInt
}
```

交集（如果一个接口包含多个非空类型集，该接口是这些类型集的交集）

```
type SignedInt interface {
   int8 | int16 | int | int32 | int64
}

type Integer interface {
   int8 | int16 | int | int32 | int64 | uint8 | uint16 | uint | uint32 | uint64
}

type Number interface {
  SignedInt
  Integer
}
```

空集（交集中的特例）

```
type SignedInt interface {
  int8 | int16 | int | int32 | int64
}

type UnsignedInt interface {
  uint8 | uint16 | uint | uint32 | uint64
}

type Integer interface {
  SignedInt
  UnsignedInt
}
```

空接口（所有类型集的集合）

```
func Do[T interface{}](n T) T {
   return n
}

func main() {
   Do[struct{}](struct{}{})
   Do[any]("abc")
}
```

底层类型（当使用 `type` 关键字声明了一个新的类型时，即便其底层类型包含在类型集内，当传入时也依旧会无法通过编译。）

```
type Int interface {
   int8 | int16 | int | int32 | int64 | uint8 | uint16 | uint | uint32 | uint64
}

type TinyInt int8

func Do[T Int](n T) T {
   return n
}

func main() {
   Do[TinyInt](1) // 无法通过编译，即便其底层类型属于Int类型集的范围内
}

解决方案：
1、向接口中加入新定义的类型
2、使用“~”，来表示底层类型，当底层类型属于该类型集，该类型就属于类型集
```

注意点

1、泛型不能作为一个类型的基本类型；

2、泛型类型无法使用类型断言；

3、匿名结构不支持泛型；

```
testStruct := struct[T int | string] {
   Name string
   Id T
}[int]{
   Name: "jack",
   Id: 1
}
```

4、匿名函数不支持自定义泛型；

```
var sum[T int | string] func (a, b T) T
sum := func[T int | string](a,b T) T{
    ...
}// 两种函数均无法编译
```

5、方法是不能拥有泛型参数的；

6、类型集无法作为类型实参；

```
type SignedInt interface {
  int8 | int16 | int | int32 | int64
}

func Do[T SignedInt](n T) T {
   return n
}

func main() {
   Do[SignedInt](1) // 无法通过编译
}
```

7、对于非接口类型，类型并集中不能有交集，例如下例中的 TinyInt 与 ~int8 有交集；

```
type Int interface {
   ~int8 | ~int16 | ~int | ~int32 | ~int64 | ~uint8 | ~uint16 | ~uint | ~uint32 | ~uint64 | TinyInt // 无法通过编译
}

type TinyInt int8

但是对于接口类型的话，就允许有交集
type Int interface {
   ~int8 | ~int16 | ~int | ~int32 | ~int64 | ~uint8 | ~uint16 | ~uint | ~uint32 | ~uint64 | TinyInt // 可以通过编译
}

type TinyInt interface {
  int8
}
```

8、类型集无法直接或间接地并入自身，同样无法并入类型约束；

```
type Floats interface {  // 代码无法通过编译
   Floats | Double
}

type Double interface {
   Floats
}
```

9、方法集无法并入类型集；

队列

```
type Queue[T any] []T

func (q *Queue[T]) Push(e T) {
  *q = append(*q, e)
}

func (q *Queue[T]) Pop(e T) (_ T) {
  if q.Size() > 0 {
    res := q.Peek()
    *q = (*q)[1:]
    return res
  }
  return
}

func (q *Queue[T]) Peek() (_ T) {
  if q.Size() > 0 {
    return (*q)[0]
  }
  return
}

func (q *Queue[T]) Size() int {
  return len(*q)
}
```

堆（必须可排序）

```
type Comparator[T any] func(a, b T) int

func (heap *BinaryHeap[T]) Peek() (_ T) {
  if heap.Size() > 0 {
    return heap.s[0]
  }
  return
}

func (heap *BinaryHeap[T]) Pop() (_ T) {
  size := heap.Size()
  if size > 0 {
    res := heap.s[0]
    heap.s[0], heap.s[size-1] = heap.s[size-1], heap.s[0]
    heap.s = heap.s[:size-1]
    heap.down(0)
    return res
  }
  return
}

func (heap *BinaryHeap[T]) Push(e T) {
  heap.s = append(heap.s, e)
  heap.up(heap.Size() - 1)
}

func (heap *BinaryHeap[T]) up(i int) {
  if heap.Size() == 0 || i < 0 || i >= heap.Size() {
    return
  }
  for parentIndex := i>>1 - 1; parentIndex >= 0; parentIndex = i>>1 - 1 {
    // greater than or equal to
    if heap.compare(heap.s[i], heap.s[parentIndex]) >= 0 {
      break
    }
    heap.s[i], heap.s[parentIndex] = heap.s[parentIndex], heap.s[i]
    i = parentIndex
  }
}

func (heap *BinaryHeap[T]) down(i int) {
  if heap.Size() == 0 || i < 0 || i >= heap.Size() {
    return
  }
  size := heap.Size()
  for lsonIndex := i<<1 + 1; lsonIndex < size; lsonIndex = i<<1 + 1 {
    rsonIndex := lsonIndex + 1

    if rsonIndex < size && heap.compare(heap.s[rsonIndex], heap.s[lsonIndex]) < 0 {
      lsonIndex = rsonIndex
    }

    // less than or equal to
    if heap.compare(heap.s[i], heap.s[lsonIndex]) <= 0 {
      break
    }
    heap.s[i], heap.s[lsonIndex] = heap.s[lsonIndex], heap.s[i]
    i = lsonIndex
  }
}

func (heap *BinaryHeap[T]) Size() int {
  return len(heap.s)
}

func NewHeap[T any](n int, c Comparator[T]) BinaryHeap[T] {
	var heap BinaryHeap[T]
	heap.s = make([]T, 0, n)
	heap.Comparator = c
	return heap
}

type Person struct {
  Age  int
  Name string
}

func main() {
  heap := NewHeap[Person](10, func(a, b Person) int {
    return cmp.Compare(a.Age, b.Age)
  })
  heap.Push(Person{Age: 10, Name: "John"})
  heap.Push(Person{Age: 18, Name: "mike"})
  heap.Push(Person{Age: 9, Name: "lili"})
  heap.Push(Person{Age: 32, Name: "miki"})
  fmt.Println(heap.Peek())
  fmt.Println(heap.Pop())
  fmt.Println(heap.Peek())
}
```

对象池

```
package main

import (
	"bytes"
	"fmt"
	"sync"
)

func NewPool[T any](newFn func() T) *Pool[T] {
	return &Pool[T]{
		pool: &sync.Pool{
			New: func() interface{} {
				return newFn()
			},
		},
	}
}

type Pool[T any] struct {
	pool *sync.Pool
}

func (p *Pool[T]) Put(v T) {
	p.pool.Put(v)
}

func (p *Pool[T]) Get() T {
	var v T
	get := p.pool.Get()
	if get != nil {
		v, _ = get.(T)
	}
	return v
}

func main() {
	bufferPool := NewPool(func() *bytes.Buffer {
		return bytes.NewBuffer(nil)
	})

	for range 100 {
		buffer := bufferPool.Get()
		buffer.WriteString("Hello, World!")
		fmt.Println(buffer.String())
		buffer.Reset()
		bufferPool.Put(buffer)
	}
}
```

###### 错误

Go 中的异常有三种级别：

- `error`：正常的流程出错，需要处理，直接忽略掉不处理程序也不会崩溃

- `panic`：很严重的问题，程序应该在处理完问题后立即退出

- `fatal`：非常致命的问题，程序应该立即退出

###### 文件

文件打开

```
func Open(name string) (*File, error)
func OpenFile(name string, flag int, perm FileMode) (*File, error)
```

```
文件描述符：
const (
   // 只读，只写，读写 三种必须指定一个
   O_RDONLY int = syscall.O_RDONLY // 以只读的模式打开文件
   O_WRONLY int = syscall.O_WRONLY // 以只写的模式打开文件
   O_RDWR   int = syscall.O_RDWR   // 以读写的模式打开文件
   // 剩余的值用于控制行为
   O_APPEND int = syscall.O_APPEND // 当写入文件时，将数据添加到文件末尾
   O_CREATE int = syscall.O_CREAT  // 如果文件不存在则创建文件
   O_EXCL   int = syscall.O_EXCL   // 与O_CREATE一起使用, 文件必须不存在
   O_SYNC   int = syscall.O_SYNC   // 以同步IO的方式打开文件
   O_TRUNC  int = syscall.O_TRUNC  // 当打开的时候截断可写的文件
)
const (
   ModeDir        = fs.ModeDir        // d: 目录
   ModeAppend     = fs.ModeAppend     // a: 只能添加
   ModeExclusive  = fs.ModeExclusive  // l: 专用
   ModeTemporary  = fs.ModeTemporary  // T: 临时文件
   ModeSymlink    = fs.ModeSymlink    // L: 符号链接
   ModeDevice     = fs.ModeDevice     // D: 设备文件
   ModeNamedPipe  = fs.ModeNamedPipe  // p: 具名管道 (FIFO)
   ModeSocket     = fs.ModeSocket     // S: Unix 域套接字
   ModeSetuid     = fs.ModeSetuid     // u: setuid
   ModeSetgid     = fs.ModeSetgid     // g: setgid
   ModeCharDevice = fs.ModeCharDevice // c: Unix 字符设备, 前提是设置了 ModeDevice
   ModeSticky     = fs.ModeSticky     // t: 黏滞位
   ModeIrregular  = fs.ModeIrregular  // ?: 非常规文件

   // 类型位的掩码. 对于常规文件而言，什么都不会设置.
   ModeType = fs.ModeType

   ModePerm = fs.ModePerm // Unix 权限位, 0o777
)
```

读取文件

```
// 将文件读进传入的字节切片
func (f *File) Read(b []byte) (n int, err error)

// 相较于第一种可以从指定偏移量读取
func (f *File) ReadAt(b []byte, off int64) (n int, err error)

func ReadFile(name string) ([]byte, error)
func ReadAll(r Reader) ([]byte, error)
```

```
func ReadFile(file *os.File) ([]byte, error) {
  buffer := make([]byte, 0, 512)
  for {
    // 当容量不足时
    if len(buffer) == cap(buffer) {
      // 扩容
      buffer = append(buffer, 0)[:len(buffer)]
    }
    // 继续读取文件
    offset, err := file.Read(buffer[len(buffer):cap(buffer)])
    // 将已写入的数据归入切片
    buffer = buffer[:len(buffer)+offset]
    // 发生错误时
    if err != nil {
      if errors.Is(err, io.EOF) {
        err = nil
      }
      return buffer, err
    }
  }
}
```

写入文件

```
// 写入字节切片
func (f *File) Write(b []byte) (n int, err error)

// 写入字符串
func (f *File) WriteString(s string) (n int, err error)

// 从指定位置开始写，当以os.O_APPEND模式打开时，会返回错误
func (f *File) WriteAt(b []byte, off int64) (n int, err error)

func WriteFile(name string, data []byte, perm FileMode) error
func WriteString(w Writer, s string) (n int, err error)
```

复制文件

```
func main() {
    // 从原文件中读取数据
  data, err := os.ReadFile("README.txt")
  if err != nil {
    fmt.Println(err)
    return
  }
    // 写入目标文件
  err = os.WriteFile("README(1).txt", data, 0666)
  if err != nil {
    fmt.Println(err)
  } else {
    fmt.Println("复制成功")
  }
}

func (f *File) ReadFrom(r io.Reader) (n int64, err error)

func main() {
  // 以只读的方式打开原文件
  origin, err := os.OpenFile("README.txt", os.O_RDONLY, 0666)
  if err != nil {
    fmt.Println(err)
    return
  }
  defer origin.Close()
  // 以只写的方式打开副本文件
  target, err := os.OpenFile("README(1).txt", os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0666)
  if err != nil {
    fmt.Println(err)
    return
  }
  defer target.Close()
  // 从原文件中读取数据，然后写入副本文件
  offset, err := target.ReadFrom(origin)
  if err != nil {
    fmt.Println(err)
    return
  }
  fmt.Println("文件复制成功", offset)
}

func Copy(dst Writer, src Reader) (written int64, err error)

func main() {
  // 以只读的方式打开原文件
  origin, err := os.OpenFile("README.txt", os.O_RDONLY, 0666)
  if err != nil {
    fmt.Println(err)
    return
  }
  defer origin.Close()
  // 以只写的方式打开副本文件
  target, err := os.OpenFile("README(1).txt", os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0666)
  if err != nil {
    fmt.Println(err)
    return
  }
  defer target.Close()
  // 复制
  written, err := io.Copy(target, origin)
  if err != nil {
    fmt.Println(err)
  } else {
    fmt.Println(written)
  }
}
```

##### 包

包的命名就是其源文件所在的名称；

包名为 main 的包为应用程序的入口包，编译不包含 main 包的源码文件时不会得到可执行文件；

一个文件夹下的所有源码文件只能属于同一个包，同样属于同一个包的源码文件不能放在多个文件夹下。

###### 包的导入

全路径导入：

包的绝对路径就是 `GOROOT/src/` 或 `GOPATH/src/` 后面包的存放路径，

import "lab/test"，源码位于`GOPATH/src/lab/test `目录下；

相对路径导入：.. 代表上级目录

相对路径只能用于导入 `GOPATH` 下的包，标准包的导入只能使用全路径导入。

###### 包的引用格式

1、标准引用格式

```
import "fmt"
```

2、自定义别名

```
import F "fmt"
```

3、省略引用格式

```
import . "fmt"
```

###### sync包和锁

sync 包里提供了互斥锁 Mutex 和读写锁 RWMutex 用于处理并发过程中可能出现同时两个或多个协程（或线程）读或写同一个变量的情况。

互斥锁Mutex

func (m *Mutex) Lock()

func (m *Mutex) Unlock()

```
package main

import (
	"fmt"
	"sync"
	"time"
)

func main() {
	var a = 0
	var lock sync.Mutex
	for i := 0; i < 10; i++ {
		go func(index int) {
			lock.Lock()
			defer lock.Unlock()
			a += 1
			fmt.Printf("index: %d, a: %d\n", index, a)
		}(i)
	}
	time.Sleep(time.Second)
}
```

读写锁

- 写操作的锁定和解锁分别是`func (*RWMutex) Lock`和`func (*RWMutex) Unlock`；

- 读操作的锁定和解锁分别是`func (*RWMutex) Rlock`和`func (*RWMutex) RUnlock`。

读写锁的区别在于：

- 当有一个 goroutine 获得写锁定，其它无论是读锁定还是写锁定都将阻塞直到写解锁；
- 当有一个 goroutine 获得读锁定，其它读锁定仍然可以继续；
- 当有一个或任意多个读锁定，写锁定将等待所有读锁定解锁之后才能够进行写锁定。

###### big包

Go语言中 math/big 包实现了大数字的多精度计算，支持 Int（有符号整数）、Rat（有理数）和 Float（浮点数）等数字类型。

Int类型

初始化

```
1、使用NewInt（）方法
x := big.NewInt(123456789999)
2、从字符串中解析
y := new(big.Int)
y.SetString("123456789012345678901234567890", 10)
3、从字节数组中获取
z := new(big.Int).SetBytes([]byte{0x12, 0x34, 0x56})
```

算数运算

```
func arithmeticOperations() {
    a := big.NewInt(100)
    b := big.NewInt(75)
    result := new(big.Int)
    
    // 加法
    result.Add(a, b)
    fmt.Printf("加法: %v + %v = %v\n", a, b, result)
    
    // 减法
    result.Sub(a, b)
    fmt.Printf("减法: %v - %v = %v\n", a, b, result)
    
    // 乘法
    result.Mul(a, b)
    fmt.Printf("乘法: %v × %v = %v\n", a, b, result)
    
    // 除法
    result.Div(a, b)
    fmt.Printf("除法: %v ÷ %v = %v\n", a, b, result)
    
    // 取模
    result.Mod(a, b)
    fmt.Printf("取模: %v mod %v = %v\n", a, b, result)
    
    // 幂运算
    result.Exp(a, big.NewInt(3), nil)
    fmt.Printf("幂运算: %v³ = %v\n", a, result)
}
```

位运算

```
func bitOperations() {
    x := big.NewInt(0b1100) // 12
    y := big.NewInt(0b1010) // 10
    result := new(big.Int)
    
    // 位与
    result.And(x, y)
    fmt.Printf("位与: %b & %b = %b\n", x, y, result)
    
    // 位或
    result.Or(x, y)
    fmt.Printf("位或: %b | %b = %b\n", x, y, result)
    
    // 异或
    result.Xor(x, y)
    fmt.Printf("异或: %b ^ %b = %b\n", x, y, result)
    
    // 非
    result.Not(x)
    fmt.Printf("非: ^%b = %b\n", x, result)
    
    // 左移
    result.Lsh(x, 2)
    fmt.Printf("左移: %b << 2 = %b\n", x, result)
    
    // 右移
    result.Rsh(x, 1)
    fmt.Printf("右移: %b >> 1 = %b\n", x, result)
}
```

比较和判断

```
func comparisonOperations() {
    a := big.NewInt(100)
    b := big.NewInt(75)
    c := big.NewInt(100)
    
    // 比较
    fmt.Printf("a.Cmp(b): %d (a > b)\n", a.Cmp(b))
    fmt.Printf("b.Cmp(a): %d (b < a)\n", b.Cmp(a))
    fmt.Printf("a.Cmp(c): %d (a == c)\n", a.Cmp(c))
    
    // 判断
    fmt.Printf("a.IsInt64(): %v\n", a.IsInt64())
    fmt.Printf("a.Sign(): %d\n", a.Sign()) // -1, 0, 1
}
```

Rat类型

```
func ratOperations() {
    // 创建有理数
    r1 := big.NewRat(1, 3)  // 1/3
    r2 := big.NewRat(2, 5)  // 2/5
    
    result := new(big.Rat)
    
    // 加法
    result.Add(r1, r2)
    fmt.Printf("有理数加法: %v + %v = %v\n", r1, r2, result)
    
    // 乘法
    result.Mul(r1, r2)
    fmt.Printf("有理数乘法: %v × %v = %v\n", r1, r2, result)
    
    // 转换为浮点数
    f, _ := result.Float64()
    fmt.Printf("浮点数表示: %v = %f\n", result, f)
    
    // 从字符串解析
    r3 := new(big.Rat)
    r3.SetString("3.14159")
    fmt.Printf("解析浮点数: %v\n", r3)
}
```

Float类型

```
func floatOperations() {
    // 创建高精度浮点数
    f1 := big.NewFloat(3.141592653589793)
    f2 := big.NewFloat(2.718281828459045)
    
    result := new(big.Float)
    
    // 设置精度
    result.SetPrec(100)
    
    // 加法
    result.Add(f1, f2)
    fmt.Printf("高精度加法: %v + %v = %v\n", f1, f2, result)
    
    // 乘法
    result.Mul(f1, f2)
    fmt.Printf("高精度乘法: %v × %v = %v\n", f1, f2, result)
    
    // 平方根
    result.Sqrt(f1)
    fmt.Printf("平方根: sqrt(%v) = %v\n", f1, result)
}
```

###### regexp包

![正则表达式](E:\笔记\go\正则表达式.jpeg)

compile-编译正则表达式

```
func Compile(expr string) (*Regexp, error)

func basicCompile() {
    // 编译正则表达式
    re, err := regexp.Compile(`^[a-z]+\[[0-9]+\]$`)
    if err != nil {
        fmt.Printf("编译错误: %v\n", err)
        return
    }
    
    // 测试匹配
    fmt.Println(re.MatchString("adam[23]"))  // true
    fmt.Println(re.MatchString("eve[7]"))    // true
    fmt.Println(re.MatchString("Job[48]"))   // false
    fmt.Println(re.MatchString("snakey"))    // false
}
```

MustCompile - 编译正则表达式（失败时panic）

```
func MustCompile(str string) *Regexp

func mustCompileExample() {
    // 如果正则表达式无效会panic
    re := regexp.MustCompile(`^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$`)
    
    emails := []string{
        "user@example.com",
        "invalid-email",
        "test@domain.co.uk",
    }
    
    for _, email := range emails {
        if re.MatchString(email) {
            fmt.Printf("有效邮箱: %s\n", email)
        } else {
            fmt.Printf("无效邮箱: %s\n", email)
        }
    }
}
```

MatchString - 字符串匹配

```
func (re *Regexp) MatchString(s string) bool

func matchStringExample() {
    re := regexp.MustCompile(`hello.*world`)
    
    texts := []string{
        "hello beautiful world",
        "hello world",
        "hi world",
        "hello there",
    }
    
    for _, text := range texts {
        if re.MatchString(text) {
            fmt.Printf("匹配: %s\n", text)
        } else {
            fmt.Printf("不匹配: %s\n", text)
        }
    }
}
```

Match - 字节切片匹配

```
func (re *Regexp) Match(b []byte) bool

func matchBytesExample() {
    re := regexp.MustCompile(`\d{3}-\d{2}-\d{4}`) // SSN格式
    
    data := []byte("我的SSN是123-45-6789，请保密")
    if re.Match(data) {
        fmt.Println("找到SSN号码")
    } else {
        fmt.Println("未找到SSN号码")
    }
}
```

MatchReader - 从Reader匹配

```
func (re *Regexp) MatchReader(r io.RuneReader) bool
```

FindString - 查找第一个匹配

```
func (re *Regexp) FindString(s string) string

func findStringExample() {
    re := regexp.MustCompile(`\d+`) // 匹配数字
    
    text := "这里有100个苹果和200个橙子"
    result := re.FindString(text)
    fmt.Printf("找到的第一个数字: %s\n", result) // 输出: 100
}
```

FindStringIndex - 查找匹配位置

```
func (re *Regexp) FindStringIndex(s string) []int

func findIndexExample() {
    re := regexp.MustCompile(`\d+`)
    text := "价格是¥1500，折扣后¥1200"
    
    index := re.FindStringIndex(text)
    if index != nil {
        start, end := index[0], index[1]
        fmt.Printf("找到数字在位置: %d-%d\n", start, end)
        fmt.Printf("匹配内容: %s\n", text[start:end])
    }
}
```

FindAllString - 查找所有匹配

```
func (re *Regexp) FindAllString(s string, n int) []string

func findAllExample() {
    re := regexp.MustCompile(`\d+`)
    text := "1只猫，2只狗，3只鸟，4条鱼"
    
    // n = -1 表示查找所有匹配
    matches := re.FindAllString(text, -1)
    fmt.Printf("所有数字: %v\n", matches) // 输出: [1 2 3 4]
    
    // n = 2 表示只查找前2个匹配
    firstTwo := re.FindAllString(text, 2)
    fmt.Printf("前两个数字: %v\n", firstTwo) // 输出: [1 2]
}
```

FindAllStringIndex - 查找所有匹配位置

```
func (re *Regexp) FindAllStringIndex(s string, n int) [][]int
```

FindStringSubmatch - 查找子匹配

```
func (re *Regexp) FindStringSubmatch(s string) []string

func submatchExample() {
    // 提取日期组成部分
    re := regexp.MustCompile(`(\d{4})-(\d{2})-(\d{2})`)
    date := "今天是2024-01-15，天气晴朗"
    
    matches := re.FindStringSubmatch(date)
    if matches != nil {
        fmt.Printf("完整匹配: %s\n", matches[0])
        fmt.Printf("年: %s\n", matches[1])
        fmt.Printf("月: %s\n", matches[2])
        fmt.Printf("日: %s\n", matches[3])
    }
}
```

FindAllStringSubmatch - 查找所有子匹配

```
func (re *Regexp) FindAllStringSubmatch(s string, n int) [][]string

func allSubmatchesExample() {
    re := regexp.MustCompile(`(\w+)=(\w+)`) // 键值对
    text := "name=张三 age=25 city=北京"
    
    allMatches := re.FindAllStringSubmatch(text, -1)
    for i, match := range allMatches {
        fmt.Printf("匹配 %d: 完整=%s, 键=%s, 值=%s\n", 
            i+1, match[0], match[1], match[2])
    }
}
```

FindStringSubmatchIndex - 子匹配位置

```
func (re *Regexp) FindStringSubmatchIndex(s string) []int
```

ReplaceAllString - 替换所有匹配

```
func (re *Regexp) ReplaceAllString(src, repl string) string

func replaceExample() {
    // 隐藏手机号中间四位
    re := regexp.MustCompile(`(\d{3})(\d{4})(\d{4})`)
    text := "我的手机是13812345678，他的手机是13987654321"
    
    // 使用$1, $2, $3引用分组
    result := re.ReplaceAllString(text, "$1****$3")
    fmt.Printf("替换后: %s\n", result)
}
```

ReplaceAllStringFunc - 使用函数替换

```
func (re *Regexp) ReplaceAllStringFunc(src string, repl func(string) string) string

func replaceFuncExample() {
    re := regexp.MustCompile(`\d+`)
    text := "价格增加了50%，销量下降了30%"
    
    result := re.ReplaceAllStringFunc(text, func(match string) string {
        num, _ := strconv.Atoi(match)
        return fmt.Sprintf("[%d]", num*2) // 将数字乘以2并加括号
    })
    
    fmt.Printf("替换后: %s\n", result) // 输出: 价格增加了[100]%，销量下降了[60]%
}
```

ReplaceAllLiteralString - 字面量替换

```
func (re *Regexp) ReplaceAllLiteralString(src, repl string) string
```

Split - 分割字符串

```
func (re *Regexp) Split(s string, n int) []string

func splitExample() {
    // 按多种分隔符分割
    re := regexp.MustCompile(`[,;]\s*`)
    text := "苹果,香蕉;橙子, 葡萄; 西瓜"
    
    parts := re.Split(text, -1)
    fmt.Printf("分割结果: %#v\n", parts)
    // 输出: []string{"苹果", "香蕉", "橙子", "葡萄", "西瓜"}
    
    // 限制分割次数
    limitedParts := re.Split(text, 3)
    fmt.Printf("限制分割: %#v\n", limitedParts)
    // 输出: []string{"苹果", "香蕉", "橙子, 葡萄; 西瓜"}
}
```

MatchString - 直接匹配字符串

```
func MatchString(pattern string, s string) (matched bool, err error)

func directMatch() {
    pattern := `^[A-Z][a-z]*$` // 首字母大写
    
    names := []string{"Alice", "bob", "Charlie", "david"}
    for _, name := range names {
        matched, err := regexp.MatchString(pattern, name)
        if err != nil {
            fmt.Printf("错误: %v\n", err)
            continue
        }
        fmt.Printf("%s: %v\n", name, matched)
    }
}
```

命名分组

```
func namedGroups() {
    text := "姓名: 张三, 年龄: 30, 城市: 北京"
    
    // 使用命名分组 (?P<name>pattern)
    re := regexp.MustCompile(`姓名:\s*(?P<name>\S+),\s*年龄:\s*(?P<age>\d+),\s*城市:\s*(?P<city>\S+)`)
    
    matches := re.FindStringSubmatch(text)
    if matches != nil {
        // 获取分组名到索引的映射
        groupNames := re.SubexpNames()
        
        result := make(map[string]string)
        for i, name := range groupNames {
            if i > 0 && name != "" { // 跳过第一个（完整匹配）和空名
                result[name] = matches[i]
            }
        }
        
        fmt.Printf("解析结果: %+v\n", result)
    }
}
```

非贪婪匹配

```
func nonGreedy() {
    text := "<div>内容1</div><div>内容2</div>"
    
    // 贪婪匹配（默认）
    greedyRe := regexp.MustCompile(`<div>.*</div>`)
    greedyMatch := greedyRe.FindString(text)
    fmt.Printf("贪婪匹配: %s\n", greedyMatch)
    
    // 非贪婪匹配
    nonGreedyRe := regexp.MustCompile(`<div>.*?</div>`)
    nonGreedyMatches := nonGreedyRe.FindAllString(text, -1)
    fmt.Printf("非贪婪匹配: %v\n", nonGreedyMatches)
}
```

复杂模式验证

```
func complexValidation() {
    // 密码强度验证：至少8位，包含大小写字母和数字
    passwordRe := regexp.MustCompile(`^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$`)
    
    passwords := []string{
        "weak",
        "weakpass",
        "Strong1",
        "VeryStrong123",
    }
    
    for _, pwd := range passwords {
        if passwordRe.MatchString(pwd) {
            fmt.Printf("✓ 强密码: %s\n", pwd)
        } else {
            fmt.Printf("✗ 弱密码: %s\n", pwd)
        }
    }
}
```

预编译正则表达式

```
// 全局变量预编译
var (
    emailRe    = regexp.MustCompile(`^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$`)
    phoneRe    = regexp.MustCompile(`^1[3-9]\d{9}$`)
    idCardRe   = regexp.MustCompile(`^\d{17}[\dXx]$`)
)

func validateUserInfo(email, phone, idCard string) bool {
    return emailRe.MatchString(email) && 
           phoneRe.MatchString(phone) && 
           idCardRe.MatchString(idCard)
}
```

避免过度使用正则表达式

```
func efficientValidation() {
    // 简单检查可以用字符串函数
    filename := "document.pdf"
    
    // 不好的做法：用正则检查文件扩展名
    re := regexp.MustCompile(`\.pdf$`)
    if re.MatchString(filename) {
        fmt.Println("PDF文件")
    }
    
    // 更好的做法：用字符串函数
    if strings.HasSuffix(filename, ".pdf") {
        fmt.Println("PDF文件")
    }
}
```

###### time包

获取时间

```
now := time.Now()
timestamp := now.Unix() //时间戳
```

##### 并发

进程：进程是程序在操作系统中的一次执行过程，系统进行资源分配和调度的一个独立单位

线程：线程是进程的一个执行实体，是 CPU 调度和分派的基本单位，它是比进程更小的能独立运行的基本单位

进程和线程关系：一个进程可以创建和撤销多个线程，同一个进程中的多个线程之间可以并发执行

多线程程序在单核心的 cpu 上运行，称为并发；多线程程序在多核心的 cpu 上运行，称为并行

并发主要由切换时间片来实现“同时”运行，并行则是直接利用多核实现多线程的运行，Go程序可以设置使用核心数，以发挥多核计算机的能力

协程：独立的栈空间，共享堆空间，调度由用户自己控制，本质上有点类似于用户级线程，这些用户级线程的调度也是自己实现的

线程：一个线程上可以跑多个协程，协程是轻量级的线程

###### channel

channel 是Go语言在语言级别提供的 goroutine 间的通信方式

channel 是类型相关的，一个 channel 只能传递一种类型的值

```
channel := make(channel, int)
```

