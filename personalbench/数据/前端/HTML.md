

### HTML

#### 标签

##### head

head标签包含文档的元数据，如文档的标题、字符集、CSS 和 JS的引用。

常见的内容：

< title >：定义页面的标题

< meta >：定义页面的元信息

< style >：定义CSS 代码的引用

< script >：定义 JS 代码的引用

< link >：链接外部的资源

```
<head>
  <meta charset="UTF-8">
  <title>我的网页</title>
  <link rel="stylesheet" href="styles.css">
  <script src="script.js"></script>
</head>
```

##### header

header 标签位于 body 内，表示文档的头部区域，通常用于放置导航栏、网站的Logo、搜索框等。

```
<header>
  <h1>我的网站</h1>
  <nav>
    <ul>
      <li><a href="#home">首页</a></li>
      <li><a href="#about">关于</a></li>
    </ul>
  </nav>
</header>
```

##### label

`<label>` 标签用于为表单控件提供标签，它的主要作用是改善表单的可访问性和用户体验。当用户点击标签时，关联的表单控件（如文本框、单选按钮、复选框等）将获得焦点，这样可以提高表单的可操作性。

1. `for` 属性：

   - 作用：`for` 属性用于指定标签关联的表单控件的 `id`。通过点击标签，可以将焦点设置到对应的控件上。

   - 示例：

     ```html
     <label for="username">用户名：</label>
     <input type="text" id="username" name="username">
     ```

2. `id` 属性：

   - 作用：`id` 属性可以为 `<label>` 标签本身指定一个唯一标识符。虽然 `<label>` 标签通常用在表单控件上，但如果为 `<label>` 添加 `id` 属性，它也可以用于其他用途，比如 JavaScript 中的操作。

   - 示例：

     ```html
     <label id="nameLabel" for="name">姓名：</label>
     ```

3. `form` 属性：

   - 作用：`form` 属性指定 `<label>` 标签关联的表单。这通常用于多个表单元素分布在不同区域时，将标签与某个特定表单关联。

   - 示例：

     ```html
     <form id="myForm">
       <label for="email" form="myForm">电子邮件：</label>
       <input type="email" id="email" name="email">
     </form>
     ```

4. `lang` 属性：

   - 作用：`lang` 属性指定 `<label>` 标签的语言。这对多语言网页和可访问性工具非常有帮助。

   - 示例：

     ```html
     <label for="age" lang="en">Age:</label>
     ```

5. `title` 属性：

   - 作用：`title` 属性为 `<label>` 标签提供额外的信息。用户将鼠标悬停在标签上时，通常会显示该信息。

   - 示例：

     ```html
     <label for="phone" title="请输入您的联系电话">电话：</label>
     ```

```html
<form>
  <label for="username">用户名：</label>
  <input type="text" id="username" name="username">
  
  <label for="password">密码：</label>
  <input type="password" id="password" name="password">
  
  <label for="subscribe">订阅：</label>
  <input type="checkbox" id="subscribe" name="subscribe">
  
  <label for="newsletter">我想订阅新闻通讯</label>
  <input type="radio" id="newsletter" name="subscription">
  
  <input type="submit" value="提交">
</form>
```

##### input

`<input>` 标签是 HTML 中用来创建用户交互式表单控件的元素，允许用户通过键盘、鼠标、触控等输入数据。根据 `type` 属性的不同，`<input>` 标签可以用于创建各种类型的输入框，如文本框、单选框、复选框、按钮等。

###### 类型

1. `type="text"`：文本输入框，允许用户输入文本。

   - 示例：

     ```html
     <input type="text" id="username" name="username" placeholder="请输入用户名">
     ```

2. `type="password"`：密码输入框，用户输入的内容会被隐藏（通常显示为星号或圆点）。

   - 示例：

     ```html
     <input type="password" id="password" name="password" placeholder="请输入密码">
     ```

3. `type="email"`：电子邮件输入框，验证用户输入的是一个有效的电子邮件地址。

   - 示例：

     ```html
     <input type="email" id="email" name="email" placeholder="请输入邮箱地址">
     ```

4. `type="number"`：数字输入框，用户只能输入数字。

   - 示例：

     ```html
     <input type="number" id="age" name="age" min="18" max="100" placeholder="请输入年龄">
     ```

5. `type="checkbox"`：复选框，用户可以选择或取消选择。

   - 示例：

     ```html
     <input type="checkbox" id="subscribe" name="subscribe" value="yes"> 订阅新闻
     ```

6. `type="radio"`：单选按钮，用户只能选择一个选项。

   - 示例：

     ```html
     <input type="radio" id="male" name="gender" value="male"> 男
     <input type="radio" id="female" name="gender" value="female"> 女
     ```

7. `type="file"`：文件选择框，允许用户选择文件上传。

   - 示例：

     ```html
     <input type="file" id="file" name="file">
     ```

8. `type="submit"`：提交按钮，点击后提交表单。

   - 示例：

     ```html
     <input type="submit" value="提交">
     ```

9. `type="button"`：普通按钮，点击后可以触发 JavaScript 事件。

   - 示例：

     ```html
     <input type="button" value="点击我" onclick="alert('按钮被点击')">
     ```

10. `type="date"`：日期选择框，允许用户选择日期。

    - 示例：

      ```html
      <input type="date" id="birthday" name="birthday">
      ```

11. `type="time"`：时间选择框，允许用户选择时间。

    - 示例：

      ```html
      <input type="time" id="meeting-time" name="meeting-time">
      ```

###### 常用属性

1. `id`：指定输入框的唯一标识符，通常与 `<label>` 的 `for` 属性配合使用。

   - 示例：

     ```html
     <input type="text" id="username" name="username">
     ```

2. `name`：指定输入框的名称，提交表单时会以该名称作为键发送给服务器。

   - 示例：

     ```html
     <input type="text" name="username">
     ```

3. `value`：指定输入框的初始值或提交时发送的值。对于按钮、复选框和单选按钮尤为重要。

   - 示例：

     ```html
     <input type="text" value="默认值">
     ```

4. `placeholder`：在输入框内显示的提示文本，当输入框为空时会显示该提示。

   - 示例：

     ```html
     <input type="text" placeholder="请输入用户名">
     ```

5. `required`：设置为必填项，用户必须输入内容才能提交表单。

   - 示例：

     ```html
     <input type="email" required>
     ```

6. `readonly`：设置为只读，用户无法更改输入框的内容。

   - 示例：

     ```html
     <input type="text" value="只读内容" readonly>
     ```

7. `disabled`：禁用输入框，用户无法与其交互。

   - 示例：

     ```html
     <input type="text" value="禁用" disabled>
     ```

8. `maxlength`：指定输入框的最大字符数。

   - 示例：

     ```html
     <input type="text" maxlength="10">
     ```

9. `min` 和 `max`：设置数字输入框的最小值和最大值，或者日期输入框的日期范围。

   - 示例：

     ```html
     <input type="number" min="1" max="10">
     ```

10. `pattern`：用于定义输入框的正则表达式模式，输入内容必须符合该模式。

    - 示例：

      ```html
      <input type="text" pattern="[A-Za-z]{3}">
      ```

11. `size`：定义输入框的显示宽度（字符数）。

    - 示例：

      ```html
      <input type="text" size="30">
      ```

12. `autofocus`：当页面加载时，自动聚焦到该输入框。

    - 示例：

      ```html
      <input type="text" autofocus>
      ```

13. `autocomplete`：开启或关闭输入框的自动完成功能。

    - 示例：

      ```html
      <input type="text" autocomplete="on">
      ```

14. `step`：定义数字输入框或日期输入框的步长，控制允许输入的值的增量。

    - 示例：

      ```html
      <input type="number" step="0.1" min="0" max="10">
      ```

```html
<form>
  <label for="username">用户名：</label>
  <input type="text" id="username" name="username" placeholder="请输入用户名" required>
  
  <label for="email">邮箱：</label>
  <input type="email" id="email" name="email" placeholder="请输入邮箱" required>
  
  <label for="age">年龄：</label>
  <input type="number" id="age" name="age" min="18" max="100">
  
  <label for="gender">性别：</label>
  <input type="radio" id="male" name="gender" value="male"> 男
  <input type="radio" id="female" name="gender" value="female"> 女
  
  <input type="submit" value="提交">
</form>
```

#### 属性

##### class

class属性能够为多个元素指定相同的类名，常被用于为一组具有相同样式或者行为的元素应用相同的 CSS 规则，或者通过 JavaScript 来批量操作这些元素。

class 使用 . 来应用CSS 规则；

在 JavaScript 中，可使用`document.getElementsByClassName()`方法来获取具有特定类名的元素集合。

```
.box {
    border: 1px solid black;
}

.highlight {
    background-color: yellow;
}
```

```
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
</head>
<body>
    <div class="myClass">这是第一个div元素。</div>
    <div class="myClass">这是第二个div元素。</div>
    <script>
        const elements = document.getElementsByClassName('myClass');
        for (let i = 0; i < elements.length; i++) {
            elements[i].style.color = 'green';
        }
    </script>
</body>
</html>
```

##### id

id 用来给单个元素赋予唯一的标识符。

在 CSS 里，使用`#`符号来选择具有特定`id`的元素。

```
#uniqueDiv {
    color: blue;
}
```

在 JavaScript 中，可使用`document.getElementById()`方法来获取具有特定`id`的元素。

```
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
</head>
<body>
    <div id="myDiv">这是一个div元素。</div>
    <script>
        const element = document.getElementById('myDiv');
        element.style.color = 'red';
    </script>
</body>
</html>
```

