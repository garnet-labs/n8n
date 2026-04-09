// ---------------------------------------------------------------------------
// Stub InstanceAiContext for isolated sub-agent evaluation
//
// Provides minimal service implementations so domain tools can be created
// without a running n8n instance. The workflow service captures
// createFromWorkflowJSON calls so we can evaluate the built workflow.
// ---------------------------------------------------------------------------

import type { WorkflowJSON } from '@n8n/workflow-sdk';

import { DEFAULT_INSTANCE_AI_PERMISSIONS } from '@n8n/api-types';

// Direct relative import — works at eval time via tsx, avoids adding cli as a dependency
import {
	resolveNodeTypeDefinition,
	listNodeDiscriminators,
	resolveBuiltinNodeDefinitionDirs,
	// eslint-disable-next-line @typescript-eslint/ban-ts-comment
	// @ts-ignore — cli is not a declared dependency but the resolver is pure filesystem code
} from '../../../../cli/src/modules/instance-ai/node-definition-resolver';
import type {
	InstanceAiContext,
	InstanceAiWorkflowService,
	InstanceAiExecutionService,
	InstanceAiCredentialService,
	InstanceAiNodeService,
	InstanceAiDataTableService,
	WorkflowDetail,
} from '../../src/types';
import type { CapturedWorkflow } from './types';

// ---------------------------------------------------------------------------
// Captured workflow accumulator
// ---------------------------------------------------------------------------

export interface WorkflowCapture {
	workflows: CapturedWorkflow[];
}

// ---------------------------------------------------------------------------
// Stub workflow service
// ---------------------------------------------------------------------------

function createStubWorkflowService(capture: WorkflowCapture): InstanceAiWorkflowService {
	let nextId = 1;

	return {
		async list() {
			return [];
		},
		async get(workflowId) {
			throw new Error(`[stub] Workflow ${workflowId} not found`);
		},
		async getAsWorkflowJSON(workflowId) {
			throw new Error(`[stub] Workflow ${workflowId} not found`);
		},
		async createFromWorkflowJSON(json: WorkflowJSON) {
			const id = `eval-wf-${String(nextId++)}`;
			capture.workflows.push({ json, success: true });
			return makeWorkflowDetail(id, json);
		},
		async updateFromWorkflowJSON(workflowId: string, json: WorkflowJSON) {
			capture.workflows.push({ json, success: true });
			return makeWorkflowDetail(workflowId, json);
		},
		async archive() {},
		async delete() {},
		async publish(workflowId) {
			return { activeVersionId: `v-${workflowId}` };
		},
		async unpublish() {},
	};
}

function makeWorkflowDetail(id: string, json: WorkflowJSON): WorkflowDetail {
	return {
		id,
		name: json.name ?? 'Eval Workflow',
		versionId: 'v1',
		activeVersionId: null,
		createdAt: new Date().toISOString(),
		updatedAt: new Date().toISOString(),
		nodes: (json.nodes ?? []).map((n) => ({
			name: n.name ?? '',
			type: n.type,
			parameters: n.parameters as Record<string, unknown> | undefined,
			position: (n.position as number[]) ?? [0, 0],
		})) as WorkflowDetail['nodes'],
		connections: (json.connections ?? {}) as Record<string, unknown>,
	};
}

// ---------------------------------------------------------------------------
// Stub services (return empty / no-op)
// ---------------------------------------------------------------------------

function createStubExecutionService(): InstanceAiExecutionService {
	return {
		async list() {
			return [];
		},
		async run() {
			return { executionId: 'exec-stub', status: 'success' };
		},
		async getStatus() {
			return { executionId: 'exec-stub', status: 'success' };
		},
		async getResult() {
			return { executionId: 'exec-stub', status: 'success' };
		},
		async stop() {
			return { success: true, message: 'stopped' };
		},
		async getDebugInfo() {
			return { executionId: 'exec-stub', nodeErrors: [], rawData: {} } as unknown as Awaited<
				ReturnType<InstanceAiExecutionService['getDebugInfo']>
			>;
		},
		async getNodeOutput() {
			return { data: [] } as unknown as Awaited<
				ReturnType<InstanceAiExecutionService['getNodeOutput']>
			>;
		},
	};
}

function createStubCredentialService(): InstanceAiCredentialService {
	return {
		async list() {
			return [];
		},
		async get() {
			throw new Error('[stub] No credentials');
		},
		async delete() {},
		async test() {
			return { success: true };
		},
	};
}

function createStubNodeService(): InstanceAiNodeService {
	const nodeDefinitionDirs = resolveBuiltinNodeDefinitionDirs();

	return {
		async listAvailable() {
			return [];
		},
		async getDescription(nodeType) {
			return {
				type: nodeType,
				displayName: nodeType,
				description: '',
				properties: [],
			} as unknown as Awaited<ReturnType<InstanceAiNodeService['getDescription']>>;
		},
		async listSearchable() {
			return [];
		},
		getNodeTypeDefinition: async (nodeType, options) => {
			const result = resolveNodeTypeDefinition(nodeType, nodeDefinitionDirs, options);
			if (result.error) {
				return { content: '', error: result.error };
			}
			return { content: result.content, version: result.version };
		},
		listDiscriminators: async (nodeType) => {
			return listNodeDiscriminators(nodeType, nodeDefinitionDirs);
		},
	};
}

interface StoredTable {
	id: string;
	name: string;
	columns: Array<{ id: string; name: string; type: string }>;
}

function createStubDataTableService(): InstanceAiDataTableService {
	const tables = new Map<string, StoredTable>();
	let nextTableId = 1;
	let nextColId = 1;

	return {
		async list() {
			return [...tables.values()].map((t) => ({
				id: t.id,
				name: t.name,
				columns: t.columns,
				createdAt: new Date().toISOString(),
				updatedAt: new Date().toISOString(),
			}));
		},
		async create(name, columns) {
			const id = `dt-${String(nextTableId++)}`;
			const storedColumns = columns.map((c) => ({
				id: `col-${String(nextColId++)}`,
				name: c.name,
				type: c.type,
			}));
			tables.set(id, { id, name, columns: storedColumns });
			return {
				id,
				name,
				columns: storedColumns,
				createdAt: new Date().toISOString(),
				updatedAt: new Date().toISOString(),
			};
		},
		async delete(dataTableId) {
			tables.delete(dataTableId);
		},
		async getSchema(dataTableId) {
			const table = tables.get(dataTableId);
			if (!table) return [];
			return table.columns.map((c, i) => ({
				id: c.id,
				name: c.name,
				type: c.type as 'string' | 'number' | 'boolean' | 'date',
				index: i,
			}));
		},
		async addColumn(dataTableId, col) {
			const table = tables.get(dataTableId);
			const colId = `col-${String(nextColId++)}`;
			const newCol = { id: colId, name: col.name, type: col.type };
			if (table) {
				table.columns.push(newCol);
			}
			return {
				id: colId,
				name: col.name,
				type: col.type,
				index: table ? table.columns.length - 1 : 0,
			};
		},
		async deleteColumn() {},
		async renameColumn() {},
		async queryRows() {
			return { count: 0, data: [] };
		},
		async insertRows(_id, rows) {
			return { insertedCount: rows.length };
		},
		async updateRows() {
			return { updatedCount: 0 };
		},
		async deleteRows() {
			return { deletedCount: 0 };
		},
	};
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface StubContextResult {
	context: InstanceAiContext;
	capture: WorkflowCapture;
}

/**
 * Create a minimal InstanceAiContext with stubbed services.
 *
 * The workflow service captures `createFromWorkflowJSON` / `updateFromWorkflowJSON`
 * calls into `capture.workflows` so the eval harness can inspect the built workflows.
 * All other services return empty/no-op results.
 */
export function createStubContext(): StubContextResult {
	const capture: WorkflowCapture = { workflows: [] };

	// Allow all tool actions without HITL approval gates
	const permissions = Object.fromEntries(
		Object.keys(DEFAULT_INSTANCE_AI_PERMISSIONS).map((k) => [k, 'always_allow' as const]),
	) as typeof DEFAULT_INSTANCE_AI_PERMISSIONS;

	const context: InstanceAiContext = {
		userId: 'eval-user',
		workflowService: createStubWorkflowService(capture),
		executionService: createStubExecutionService(),
		credentialService: createStubCredentialService(),
		nodeService: createStubNodeService(),
		dataTableService: createStubDataTableService(),
		permissions,
	};

	return { context, capture };
}
