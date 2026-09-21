<script setup lang="ts">
import { onLaunch, onShow, onHide } from "@dcloudio/uni-app";
onLaunch(() => {
  console.log("App Launch");
});
onShow(() => {
  console.log("App Show");
});
onHide(() => {
  console.log("App Hide");
});
</script>
<style>
/* 全局设计 token：同一颜色此前散落在 9 个页面里硬编码（仅 #4f7cff 就出现 45 次），
   改色要逐文件搜改。统一收口到 CSS 变量，各页 var(--…) 引用。
   选择器同时写 page（uni-app 页面根）和 :root（H5 根），两端都能拿到变量。 */
page,
:root {
  /* 主品牌色：按钮 / 链接 / 选中态 */
  --brand: #4f7cff;
  /* 文字四档（由深到浅） */
  --ink: #1f2d50;
  --ink-2: #33405f;
  --ink-3: #6a7591;
  --ink-4: #8a94ad;
  /* 页面 / 卡片底色 */
  --bg: #f4f6fb;
  --soft: #eef2fb;
  /* 描边 / 分隔线 */
  --line: #c5cee0;
  /* 语义色：对错 + 错误浅底 */
  --success: #07c160;
  --danger: #fa5151;
  --danger-bg: #fdecec;
}
</style>
