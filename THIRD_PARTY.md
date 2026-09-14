# 神经后端来源与署名

DOOMFLY: https://github.com/nftechie/doomfly ，固定提交 71ecf53d78eaffaf1a57ed7b0ccf5d458abc9f33。上游原创 Python/C++ 代码按 MIT 使用；完整许可与第三方声明保存在 vendor/doomfly/LICENSE、THIRD_PARTY.md 和 licenses/ 中。源码压缩包不捆绑 vendor，安装脚本从固定版本获取。

MaleCNS v1.0：来源 https://male-cns.janelia.org/download/ ，感谢 MaleCNS collaboration（包括 HHMI Janelia FlyEM、Cambridge、MRC LMB 与 Google Research 及发布所列作者）。上游注明数据采用 CC BY 4.0，具体见其 THIRD_PARTY.md 和 licenses/CC-BY-4.0.txt。输入版本、URL 与校验和保存在 research/upstream-lock.json。

FlyCoder 使用上游数据转换与固定权重近似 LIF 模型，另行设计任务状态到亮度、神经活动到编程动作的映射。该映射为人工工程选择，非数据作者提供或验证的自然功能。报告、神经元 ID 映射等数据派生产物应保留署名。没有宣称神经动力学、生物学习或果蝇代码理解获得验证。
