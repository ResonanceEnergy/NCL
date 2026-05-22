// CalendarCityPicker.swift
// Bottom sheet that lists the 7 NCL cities and reports the user's pick.
// Presented from CalendarView's header.

import SwiftUI

struct CalendarCityPicker: View {
    @Binding var selected: CalendarCity
    @Environment(\.dismiss) private var dismiss
    let onPick: (CalendarCity) -> Void

    var body: some View {
        NavigationStack {
            List(CalendarCity.allCases) { city in
                Button {
                    selected = city
                    onPick(city)
                    dismiss()
                } label: {
                    HStack(spacing: 12) {
                        Text(city.emoji)
                            .font(.system(size: 28))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(city.displayName)
                                .font(AppTheme.headlineFont)
                                .foregroundColor(.white)
                            Text(city.country)
                                .font(AppTheme.captionFont)
                                .foregroundColor(.white.opacity(0.6))
                        }
                        Spacer()
                        if city == selected {
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundColor(AppTheme.accent)
                        }
                    }
                    .padding(.vertical, 6)
                }
                .listRowBackground(AppTheme.cardBackground)
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(AppTheme.background)
            .navigationTitle("Select City")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                        .tint(AppTheme.accent)
                }
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }
}
