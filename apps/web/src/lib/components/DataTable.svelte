<script lang="ts" module>
  import type { Snippet } from 'svelte';

  export type DataTableColumn<Row> = {
    key: string;
    header: string;
    cell?: Snippet<[Row]>;
  };
</script>

<script lang="ts" generics="Row extends Record<string, unknown>">
  type Props = {
    rows: Row[];
    columns: DataTableColumn<Row>[];
    rowKey: (row: Row) => string;
    onRowClick?: (row: Row) => void;
    caption?: string;
  };

  let { rows, columns, rowKey, onRowClick, caption }: Props = $props();

  function handleKeydown(event: KeyboardEvent, row: Row): void {
    if (!onRowClick) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onRowClick(row);
    }
  }
</script>

<div class="datatable-wrap">
  <table class="datatable" data-testid="data-table">
    {#if caption}
      <caption>{caption}</caption>
    {/if}
    <thead>
      <tr>
        {#each columns as col (col.key)}
          <th scope="col">{col.header}</th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each rows as row (rowKey(row))}
        <tr
          class:clickable={!!onRowClick}
          data-testid="data-table-row"
          role={onRowClick ? 'link' : undefined}
          tabindex={onRowClick ? 0 : undefined}
          onclick={onRowClick ? () => onRowClick(row) : undefined}
          onkeydown={onRowClick ? (e) => handleKeydown(e, row) : undefined}
        >
          {#each columns as col (col.key)}
            <td>
              {#if col.cell}
                {@render col.cell(row)}
              {:else}
                {String(row[col.key] ?? '')}
              {/if}
            </td>
          {/each}
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .datatable-wrap {
    overflow-x: auto;
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    background: var(--surface);
  }
  table.datatable {
    width: 100%;
    border-collapse: collapse;
    color: var(--ink);
    font-size: 14px;
  }
  caption {
    text-align: left;
    padding: 8px 12px;
    color: var(--mute);
    font-size: 13px;
  }
  thead th {
    text-align: left;
    padding: 10px 12px;
    background: var(--surface-2);
    border-bottom: 1px solid var(--border);
    color: var(--mute);
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  tbody td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
  }
  tbody tr:last-child td {
    border-bottom: none;
  }
  tbody tr.clickable {
    cursor: pointer;
  }
  tbody tr.clickable:hover {
    background: var(--surface-2);
  }
  tbody tr.clickable:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }
</style>
