/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { DocumentType } from './DocumentType';
/**
 * Used for syncing documents.
 * - id: If present, we keep/update it. If None, we create a new record.
 */
export type PickupDocumentUpdate = {
    document_type: DocumentType;
    file_url: string;
    file_name: string;
    id?: (string | null);
};

