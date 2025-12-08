// src/components/SortHeader.jsx
import { thStyle } from "../ui/table";

function SortHeader({ label, field, sortField, sortDirection, onSort }) {
  const isActive = sortField === field;
  const arrow = !isActive ? "" : sortDirection === "ASC" ? " ▲" : " ▼";

  return (
    <th
      style={thStyle}
      onClick={() => onSort(field)}
      title={isActive ? `Sorted by ${label} (${sortDirection})` : `Sort by ${label}`}
    >
      {label}
      {arrow}
    </th>
  );
}

export default SortHeader;