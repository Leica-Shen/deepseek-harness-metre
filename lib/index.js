/**
 * metre —— 把随包携带的 SKILL.md 注册成 Harness skill。
 *
 * 只做一件事：读包根目录的 SKILL.md，解析 frontmatter，把正文里的
 * ${SKILL_DIR} 替换成包内绝对路径后交给 skill registry。
 *
 * 为什么不用 @deepseek-ai/dsh-skill-filesystem：那个 provider 从固定目录
 * 扫描（~/.agents/skills 等），而本包要「装进任意 profile 也能用」，
 * 所以自己注册一个只读包内文件的 provider。
 */
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

export const name = 'metre';
export const inject = ['skills'];

// 产品名：格律（Metre）。
const SKILL_NAME = 'metre';
const ROOT_URL = new URL('../', import.meta.url);
const SKILL_URL = new URL('SKILL.md', ROOT_URL);
const SKILL_DIR = fileURLToPath(ROOT_URL).replace(/[\\/]+$/, '').replaceAll('\\', '/');
const RANK = 600;

function splitFrontmatter(raw) {
  const m = /^---\r?\n([\s\S]*?)\r?\n---[ \t]*\r?\n?/.exec(raw);
  if (!m) return { attrs: {}, body: raw };
  const attrs = {};
  for (const line of m[1].split(/\r?\n/)) {
    const i = line.indexOf(':');
    if (i <= 0) continue;
    attrs[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return { attrs, body: raw.slice(m[0].length) };
}

async function load(name = SKILL_NAME) {
  const raw = await readFile(SKILL_URL, 'utf8');
  const { attrs, body } = splitFrontmatter(raw);
  return {
    name,
    description: attrs.description || '',
    whenToUse: attrs.whenToUse,
    content: body.replaceAll('${SKILL_DIR}', () => SKILL_DIR),
    path: fileURLToPath(SKILL_URL),
    resourceBase: { kind: 'directory', path: SKILL_DIR },
    locator: SKILL_URL,
  };
}

export function apply(ctx, config = {}) {
  const rank = Number.isInteger(config.rank) && config.rank > 0 ? config.rank : RANK;
  ctx.skills.registerProvider(() => ({
    name: SKILL_NAME,
    async list() {
      const row = await load();
      const rows = [{
        name: row.name,
        description: row.description,
        invocation: { modelInvocable: true, userInvocable: true },
        provider: SKILL_NAME,
        source: 'bundled',
        resourceBase: row.resourceBase,
        rank,
        locator: row.locator,
      }];
      return rows;
    },
    async get(candidate) {
      const row = await load(candidate?.name || SKILL_NAME);
      return {
        name: row.name,
        description: row.description,
        whenToUse: row.whenToUse,
        invocation: { modelInvocable: true, userInvocable: true },
        provider: SKILL_NAME,
        source: 'bundled',
        resourceBase: row.resourceBase,
        content: row.content,
        path: row.path,
      };
    },
  }));
}
