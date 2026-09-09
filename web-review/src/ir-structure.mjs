import { Unsupported } from './core.mjs';

// This is a structural explanation, not an equivalence checker. Bound names
// use lexical distances; input names, operator order and literal DATA remain
// significant. Location/label metadata is ignored only at known IR positions.
export function compareIRStructure(before, after, { nodeLimit = 4096, textLimit = 1048576, changeLimit = 64 } = {}) {
  try {
    for (const [limit, hard] of [[nodeLimit, 16384], [textLimit, 8388608], [changeLimit, 1024]]) {
      if (!Number.isSafeInteger(limit) || limit < 1 || limit > hard) throw new Unsupported('IR 구조 비교 제한이 잘못됐습니다.');
    }
    let nodes = 0, text = 0;
    const interned = new Map();
    const knownKeys = (value, allowed) => {
      if (Object.keys(value).some(key => !allowed.includes(key))) throw new Unsupported('새로운 IR 필드를 조용히 무시하여 구조가 같다고 표시할 수 없습니다.');
    };
    function normalize(node, scope, path, depth) {
      if (++nodes > nodeLimit || depth > 128) throw new Unsupported('IR 구조 비교의 노드·깊이 제한을 초과했습니다.');
      const head = { kind: node.kind }, children = [], child = (role, value, suffix, environment = scope) => {
        const childNode = normalize(value, environment, path + suffix, depth + 1);
        children.push({ role, node: childNode }); return childNode;
      };
      const extra = [];
      if (Object.hasOwn(node, 'valueProfile')) head.valueProfile = node.valueProfile;
      if (Object.hasOwn(node, 'generatedOperation')) head.generatedOperation = node.generatedOperation;
      switch (node.kind) {
        case 'literal': extra.push('value'); head.value = node.value; break;
        case 'input': extra.push('name'); head.name = node.name; break;
        case 'local': {
          extra.push('name', 'label');
          const index = scope.lastIndexOf(node.name);
          if (index < 0) throw new Unsupported('IR 구조 비교에서 지역 값의 범위를 찾지 못했습니다.');
          head.bindingDistance = scope.length - index - 1; break;
        }
        case 'let':
          extra.push('name', 'label', 'initializer', 'value', 'body', 'bindingRole', 'bindingKey', 'argumentIndex', 'provided');
          for (const field of ['bindingRole', 'bindingKey', 'argumentIndex', 'provided']) if (Object.hasOwn(node, field)) head[field] = node[field];
          child('value', node.value, '.value'); child('body', node.body, '.body', [...scope, node.name]); break;
        case 'conditional':
          extra.push('condition', 'yes', 'no');
          child('condition', node.condition, '.condition'); child('yes', node.yes, '.yes'); child('no', node.no, '.no'); break;
        case 'binary':
          extra.push('op', 'left', 'right'); head.op = node.op;
          child('left', node.left, '.left'); child('right', node.right, '.right'); break;
        case 'unary':
        case 'intrinsic':
        case 'object-child':
          extra.push('value');
          if (node.kind === 'unary') { extra.push('op'); head.op = node.op; }
          if (node.kind === 'intrinsic') { extra.push('name'); head.name = node.name; }
          child('value', node.value, '.value'); break;
        case 'access':
          extra.push('base', 'steps'); child('base', node.base, '.base');
          head.steps = node.steps.map((step, index) => {
            knownKeys(step, ['key', 'optional', 'value', 'source']);
            const result = { optional: !!step.optional };
            if (Object.hasOwn(step, 'key')) result.key = step.key;
            if (step.value) { result.computed = true; child(`key:${index}`, step.value, `.steps[${index}].value`); }
            return result;
          }); break;
        case 'array':
          extra.push('items'); node.items.forEach((item, index) => child(`item:${index}`, item, `.items[${index}]`)); break;
        case 'array-filter':
          extra.push('base', 'predicate', 'parameter', 'parameterLabel', 'parameterSource');
          child('base', node.base, '.base'); child('predicate', node.predicate, '.predicate', [...scope, node.parameter]); break;
        case 'array-concat':
          extra.push('base', 'arguments'); child('base', node.base, '.base');
          node.arguments.forEach((item, index) => child(`argument:${index}`, item, `.arguments[${index}]`)); break;
        case 'record':
          extra.push('projection', 'properties'); if (node.projection) head.projection = node.projection;
          head.properties = node.properties.map((property, index) => {
            knownKeys(property, ['name', 'spread', 'value', 'source']);
            child(`property:${index}`, property.value, `.properties[${index}].value`);
            return property.spread ? { spread: true } : { name: property.name };
          }); break;
        case 'jsx':
          extra.push('tag', 'attributes', 'children'); head.tag = node.tag;
          head.attributes = node.attributes.map((attribute, index) => {
            knownKeys(attribute, ['name', 'value', 'source']);
            child(`attribute:${index}`, attribute.value, `.attributes[${index}].value`); return attribute.name;
          });
          node.children.forEach((item, index) => child(`child:${index}`, item, `.children[${index}]`)); break;
        default: throw new Unsupported(`IR 구조 비교에서 지원하지 않는 연산: ${node.kind}`);
      }
      knownKeys(node, ['kind', 'source', 'definition', 'valueProfile', 'generatedOperation', ...extra]);
      const shape = JSON.stringify(head), key = JSON.stringify([head, children.map(row => [row.role, row.node.id])]);
      text += key.length;
      if (text > textLimit) throw new Unsupported('IR 구조 비교의 내용 크기 제한을 초과했습니다.');
      if (!interned.has(key)) interned.set(key, interned.size + 1);
      return { id: interned.get(key), shape, kind: node.kind, path, source: node.source, children };
    }
    const a = normalize(before, [], '$', 0), beforeNodes = nodes, b = normalize(after, [], '$', 0);
    const changes = [];
    const location = node => ({ path: node.path, kind: node.kind, source: node.source });
    function diff(left, right) {
      if (left.id === right.id) return;
      if (changes.length >= changeLimit) throw new Unsupported('IR 구조 변경 개수 제한을 초과했습니다. 일부만 완성본으로 표시하지 않습니다.');
      if (left.kind === 'conditional' && right.kind === 'conditional' && left.shape === right.shape && left.children[1].node.id === right.children[1].node.id && left.children[2].node.id === right.children[2].node.id) {
        changes.push({ kind: 'condition-changed', before: location(left.children[0].node), after: location(right.children[0].node),
          sameBranchStructure: true, branches: ['yes', 'no'].map((branch, index) => ({ branch, before: location(left.children[index + 1].node), after: location(right.children[index + 1].node) })) });
      } else if (left.shape === right.shape && left.children.length === right.children.length && left.children.every((row, index) => row.role === right.children[index].role)) {
        for (let index = 0; index < left.children.length; index++) diff(left.children[index].node, right.children[index].node);
      } else changes.push({ kind: 'structure-replaced', before: location(left), after: location(right) });
    }
    diff(a, b);
    return { status: 'ir-structural-comparison', sameStructure: a.id === b.id, changes, beforeNodes, afterNodes: nodes - beforeNodes,
      scope: '알려진 위치·표시 이름을 제외하고 지역 바인딩 범위를 유지한 IR 구조 비교; 같은 갈래 구조가 같은 결과값·전체 행동·기획 의도를 보증하지 않음' };
  } catch (error) {
    if (!(error instanceof Unsupported)) throw error;
    return { status: 'not-generated', reason: error.message };
  }
}
