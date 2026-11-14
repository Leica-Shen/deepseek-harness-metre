# 发布到 GitHub（三步）

仓库已就绪：`git init` 完成、首个提交已建（分支 `main`）。

## 1. 用 SSH（推荐）

本机已生成一把专用密钥：`~/.ssh/metre_github`（无口令）。

```bash
# 把公钥加到 GitHub：Settings → SSH and GPG keys → New SSH key
pbcopy < ~/.ssh/metre_github.pub
open "https://github.com/settings/ssh/new"
```

粘贴、命名 `metre-opensource`、保存。然后：

```bash
ssh -T git@github.com            # 应显示 Hi <你的账号>!
cd ~/Desktop/Create/metre
git remote add origin git@github.com:<你的账号>/metre.git
git push -u origin main
```

仓库需先在 GitHub 上建好（Public，不要勾 README / .gitignore）。
建库链接：<https://github.com/new?name=metre&visibility=public>

## 2. 用 HTTPS + PAT

```bash
cd ~/Desktop/Create/metre
git remote add origin https://github.com/<你的账号>/metre.git
git push -u origin main           # 用户名 <你的账号>，密码填 PAT
```

## 3. 校验

```bash
git ls-remote origin | head -3
open "https://github.com/<你的账号>/metre"
```

## 仓库内容

```
README.md  LICENSE(MIT)  SKILL.md  requirements.txt  package.json
studio/    design/       examples/coffee/            tests/
```

不含：`__pycache__`、构建产物（`*.pptx`）、体检报告。
